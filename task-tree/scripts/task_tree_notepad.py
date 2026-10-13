"""Bounded shared context with a managed header; callers hold the store lock."""

import hashlib
import json
import os
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

MAX_WORDS = 200
MAX_TEXT_BYTES = 8192
RESERVED_PREFIX = ".task-tree-notepad"


def filename(tree_path: str) -> str:
    """Return the canonical note name or a legacy filename-bound name for preservation."""
    name = Path(tree_path).name
    suffix = "" if name == "tree.json" else "-" + hashlib.sha256(os.fsencode(name)).hexdigest()
    return RESERVED_PREFIX + suffix + ".md"


def path_for(tree_path: str) -> Path:
    return Path(tree_path).parent / "shared" / filename(tree_path)


def preserve_legacy_note(old_tree_path: str, canonical_tree_path: str) -> None:
    """Copy an exact filename-bound managed note before tree JSON rename.

    The old note is intentionally retained as recovery material. Existing
    notepad validation remains the authority for managed path/header/content.
    """
    old_text = read(old_tree_path)
    if old_text is None:
        return
    canonical_text = read(canonical_tree_path)
    if canonical_text is not None and canonical_text != old_text:
        raise ValueError(
            "conflicting canonical and legacy notepad texts; neither note was changed"
        )
    if canonical_text is None:
        replace(canonical_tree_path, old_text)


def _header(tree_path: str) -> str:
    return "<!-- task-tree managed notepad: " + json.dumps(Path(tree_path).name) + " -->\n"


def validate_text(text: str) -> None:
    if len(text.split()) > MAX_WORDS:
        raise ValueError(f"notepad exceeds {MAX_WORDS} words; existing note unchanged")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"notepad exceeds {MAX_TEXT_BYTES} UTF-8 bytes; existing note unchanged")


@contextmanager
def _shared_directory(tree_path: str, *, create: bool = False):
    path = path_for(tree_path).parent
    if create:
        os.makedirs(path, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except FileNotFoundError:
        yield None
        return
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _read_owned(tree_path: str, directory: int) -> str | None:
    try:
        descriptor = os.open(filename(tree_path), os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, "rb") as stream:
        observed = os.fstat(stream.fileno())
        if not stat.S_ISREG(observed.st_mode):
            raise ValueError("notepad file is not a regular file")
        bound = MAX_TEXT_BYTES + len(_header(tree_path).encode("utf-8"))
        raw = stream.read(bound + 1)
        if len(raw) > bound:
            raise ValueError("notepad file exceeds its bounded storage contract")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("notepad is not valid UTF-8") from error
        header = _header(tree_path)
        if not content.startswith(header):
            raise ValueError("notepad collision: missing or foreign task-tree ownership header")
        text = content[len(header):]
        validate_text(text)
        return text


def read(tree_path: str) -> str | None:
    with _shared_directory(tree_path) as directory:
        return None if directory is None else _read_owned(tree_path, directory)


def replace(tree_path: str, text: str) -> None:
    validate_text(text)
    with _shared_directory(tree_path, create=True) as directory:
        _read_owned(tree_path, directory)  # Refuse collision before changing anything.
        temporary = RESERVED_PREFIX + ".write-" + uuid.uuid4().hex
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o666, dir_fd=directory)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write((_header(tree_path) + text).encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, filename(tree_path), src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass


def clear(tree_path: str) -> None:
    with _shared_directory(tree_path) as directory:
        if directory is None or _read_owned(tree_path, directory) is None:
            return
        os.unlink(filename(tree_path), dir_fd=directory)
        os.fsync(directory)


def snapshot(tree_path: str) -> dict:
    """Display errors explicitly without obscuring an already committed task edit."""
    payload = {"path": str(path_for(tree_path)), "status": "missing", "text": None, "error": None}
    try:
        text = read(tree_path)
        if text is not None:
            payload.update(status="ready", text=text)
    except (OSError, ValueError) as error:
        payload.update(status="error", error=str(error))
    return payload


def render(payload: dict) -> str:
    heading = "Tree-wide notepad"
    if payload["status"] == "error":
        return heading + "\nUnavailable: " + payload["error"]
    if payload["status"] == "missing":
        return heading + "\n(not set)"
    return heading + "\n" + (payload["text"] or "(empty)")
