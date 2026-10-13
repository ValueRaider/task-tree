import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_task_tree_runtime_deployment import deploy_runtime, run_runtime, tree, write_json


def test_sole_noncanonical_json_is_renamed_byte_for_byte_on_read(tmp_path):
    project, script = deploy_runtime(tmp_path)
    store = project / "chosen"
    original = store / "legacy-name.json"
    raw = json.dumps(tree(), separators=(",", ":")).encode() + b"\n"
    original.parent.mkdir()
    original.write_bytes(raw)

    result = run_runtime(project, script, "--tree-dir", str(store), "snapshot", "--json")

    assert result.returncode == 0, result.stderr
    assert (store / "tree.json").read_bytes() == raw
    assert not original.exists()
    assert f"{original} to {store / 'tree.json'}" in result.stderr


def test_deprecated_tree_file_converts_to_parent_and_warns(tmp_path):
    project, script = deploy_runtime(tmp_path)
    legacy = project / "chosen" / "legacy-name.json"
    raw = json.dumps(tree(), separators=(",", ":")).encode() + b"\n"
    legacy.parent.mkdir()
    legacy.write_bytes(raw)

    result = run_runtime(project, script, "--tree-file", str(legacy), "snapshot", "--json")

    assert result.returncode == 0, result.stderr
    assert not legacy.exists()
    assert (legacy.parent / "tree.json").read_bytes() == raw
    assert f"--tree-dir {legacy.parent}" in result.stderr


def test_empty_read_does_not_create_tree_json_and_directories_are_independent(tmp_path):
    project, script = deploy_runtime(tmp_path)
    a, b = project / "a", project / "b"
    a_result = run_runtime(project, script, "--tree-dir", str(a), "snapshot", "--json")
    b_result = run_runtime(project, script, "--tree-dir", str(b), "add", "B")

    assert a_result.returncode == b_result.returncode == 0
    assert not (a / "tree.json").exists()
    assert json.loads((b / "tree.json").read_text())["nodes"][0]["summary"] == "B"
    assert not (a / "files").exists() and not (a / "shared").exists()


@pytest.mark.parametrize("selector", ["tree-dir", "tree-file"])
@pytest.mark.parametrize("operation", ["scan-prune", "clear-prune", "reset"])
def test_multiple_json_precedes_cleanup_and_preserves_store_bytes(
    tmp_path, selector, operation
):
    project, script = deploy_runtime(tmp_path)
    store = project / "selected"
    one, two = store / "legacy.json", store / "other.json"
    one.parent.mkdir()
    valid_empty_tree = {
        "schema_version": 2,
        "next_id": 1,
        "active_id": None,
        "root_ids": [],
        "nodes": [],
    }
    one_bytes = (json.dumps(valid_empty_tree, separators=(",", ":")) + "\n").encode()
    two_bytes = (json.dumps(valid_empty_tree, indent=2) + "\n").encode()
    one.write_bytes(one_bytes)
    two.write_bytes(two_bytes)
    sentinel = store / "files" / "1" / "sentinel.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"keep exactly\x00\n")
    before = (one.read_bytes(), two.read_bytes(), sentinel.read_bytes())

    args = ["--tree-dir", str(store)] if selector == "tree-dir" else ["--tree-file", str(one)]
    if operation == "scan-prune":
        args.extend(["scan-files", "--prune"])
    elif operation == "clear-prune":
        args.extend(["clear", "--prune-files"])
    else:
        args.append("reset")

    result = run_runtime(project, script, *args)

    assert result.returncode == 2
    assert "multiple JSON files" in result.stderr
    assert (one.read_bytes(), two.read_bytes(), sentinel.read_bytes()) == before
    assert not (store / "tree.json").exists()


def test_legacy_filename_notepad_is_copied_but_retained(tmp_path):
    project, script = deploy_runtime(tmp_path)
    store = project / "selected"
    old_name = "legacy-name.json"
    old_tree = store / old_name
    write_json(old_tree, tree())
    name_hash = hashlib.sha256(os.fsencode(old_name)).hexdigest()
    old_note = store / "shared" / f".task-tree-notepad-{name_hash}.md"
    old_note.parent.mkdir(parents=True)
    old_note.write_text(f'<!-- task-tree managed notepad: "{old_name}" -->\nkeep this note\n')

    result = run_runtime(project, script, "--tree-dir", str(store), "snapshot")

    assert result.returncode == 0, result.stderr
    canonical_note = store / "shared" / ".task-tree-notepad.md"
    assert canonical_note.read_text() == "<!-- task-tree managed notepad: \"tree.json\" -->\nkeep this note\n"
    assert old_note.exists()


def test_selected_directory_operation_waits_on_canonical_lock(tmp_path):
    project, script = deploy_runtime(tmp_path)
    store = project / "selected"
    old = store / "legacy.json"
    write_json(old, tree())
    lock = store / "tree.json.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    handle = lock.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    process = subprocess.Popen(
        [sys.executable, str(script), "--tree-dir", str(store), "snapshot", "--json"],
        cwd=project,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        # Observe the child blocked in the kernel's lock wait, rather than
        # treating lack of output or elapsed time as evidence of serialization.
        deadline = time.monotonic() + 5
        wait_channel = ""
        while time.monotonic() < deadline:
            try:
                wait_channel = Path(f"/proc/{process.pid}/wchan").read_text().strip()
            except FileNotFoundError:
                break
            if "lock" in wait_channel.lower():
                break
            if process.poll() is not None:
                break
            time.sleep(0.01)
        assert "lock" in wait_channel.lower(), f"child was not observed waiting on lock: {wait_channel}"
        # The lock holder controls release after that explicit checkpoint.
        canonical_bytes = old.read_bytes()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=10)
    finally:
        handle.close()
        if process.poll() is None:
            process.kill()
            process.wait()

    assert process.returncode == 0, stderr
    assert json.loads(stdout)["active"]["summary"] == "Task"
    assert not old.exists()
    assert (store / "tree.json").read_bytes() == canonical_bytes
    assert "canonicalized tree store" in stderr
