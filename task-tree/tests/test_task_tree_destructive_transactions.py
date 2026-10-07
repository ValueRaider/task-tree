from __future__ import annotations

import builtins
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SCRIPT = TEST_DIR.parent / "scripts" / "task_tree.py"

spec = importlib.util.spec_from_file_location("task_tree_destructive_transactions", SCRIPT)
task_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_tree)


def write_attached_tree(tree_path: Path, *, files_dir: str | None = None) -> Path:
    artifact = tree_path.parent / "files" / "1"
    artifact.mkdir(parents=True)
    (artifact / "evidence.txt").write_text("preserve", encoding="utf-8")
    attached = str(artifact) if files_dir is None else files_dir
    data = {
        "schema_version": 2,
        "next_id": 2,
        "active_id": 1,
        "root_ids": [1],
        "nodes": [
            {
                "id": 1,
                "children": [],
                "summary": "Destructive target",
                "body": "",
                "status": "in_progress",
                "closeout_reviewed": False,
                "files_dir": attached,
                "events": {},
            }
        ],
    }
    tree_path.parent.mkdir(parents=True, exist_ok=True)
    tree_path.write_text(json.dumps(data), encoding="utf-8")
    return artifact


def load_tree(tree_path: Path) -> dict:
    return json.loads(tree_path.read_text(encoding="utf-8"))


def command_args(tree_path: Path, command: str) -> list[str]:
    base = ["--tree-file", str(tree_path)]
    if command == "delete":
        return [*base, "delete", "1", "--json"]
    if command == "prune-files":
        return [*base, "prune-files", "1", "--json"]
    if command == "clear":
        return [*base, "clear", "--prune-files", "--json"]
    if command == "reset":
        return [*base, "reset", "--json"]
    raise AssertionError(command)


@pytest.mark.parametrize("command", ["delete", "prune-files", "clear", "reset"])
def test_commit_failure_never_starts_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    before = tree_path.read_bytes()

    def fail_commit(_store, _data):
        raise OSError("injected commit failure")

    monkeypatch.setattr(task_tree.TaskTreeStore, "_write_unlocked", fail_commit)

    with pytest.raises(OSError, match="injected commit failure"):
        task_tree.main(command_args(tree_path, command))

    assert capsys.readouterr().out == ""
    assert tree_path.read_bytes() == before
    assert (artifact / "evidence.txt").read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("command", ["delete", "prune-files", "clear", "reset"])
def test_cleanup_failure_keeps_committed_metadata_and_reports_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)

    def fail_cleanup(_path):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(task_tree.shutil, "rmtree", fail_cleanup)

    exit_code = task_tree.main(command_args(tree_path, command))

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["metadata_committed"] is True
    assert payload["cleanup"]["removed"] == []
    assert len(payload["cleanup"]["failed"]) == 1
    assert "injected cleanup failure" in payload["cleanup"]["failed"][0]["error"]
    assert (artifact / "evidence.txt").is_file()
    data = load_tree(tree_path)
    if command == "prune-files":
        assert data["nodes"][0]["files_dir"] is None
        assert "files_detached_at" in data["nodes"][0]["events"]
        assert "files_pruned_at" not in data["nodes"][0]["events"]
    else:
        assert data["nodes"] == []


@pytest.mark.parametrize("command", ["delete", "prune-files", "clear", "reset"])
def test_post_replace_error_never_starts_cleanup_and_leaves_recoverable_residue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    real_write = task_tree.TaskTreeStore._write_unlocked
    cleanup_started = False

    def replace_then_fail(store, data):
        real_write(store, data)
        raise OSError("injected post-replace failure")

    def track_cleanup(_path):
        nonlocal cleanup_started
        cleanup_started = True

    monkeypatch.setattr(task_tree.TaskTreeStore, "_write_unlocked", replace_then_fail)
    monkeypatch.setattr(task_tree.shutil, "rmtree", track_cleanup)

    with pytest.raises(OSError, match="post-replace"):
        task_tree.main(command_args(tree_path, command))

    assert capsys.readouterr().out == ""
    assert cleanup_started is False
    assert (artifact / "evidence.txt").is_file()
    data = load_tree(tree_path)
    if command == "prune-files":
        assert data["nodes"][0]["files_dir"] is None
    else:
        assert data["nodes"] == []


@pytest.mark.parametrize("command", ["delete", "prune-files", "clear", "reset"])
def test_cleanup_runs_only_after_the_metadata_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    committed = False
    real_write = task_tree.TaskTreeStore._write_unlocked
    real_rmtree = task_tree.shutil.rmtree

    def tracked_write(store, data):
        nonlocal committed
        real_write(store, data)
        committed = True

    def checked_cleanup(path):
        assert committed is True
        return real_rmtree(path)

    monkeypatch.setattr(task_tree.TaskTreeStore, "_write_unlocked", tracked_write)
    monkeypatch.setattr(task_tree.shutil, "rmtree", checked_cleanup)

    exit_code = task_tree.main(command_args(tree_path, command))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"]["removed"] == [
        {"kind": "task", "path": str(artifact), "task_id": 1}
    ]
    assert not artifact.exists()


@pytest.mark.parametrize("command", ["delete", "prune-files", "clear", "reset"])
def test_output_failure_occurs_after_commit_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)

    def fail_output(*_args, **_kwargs):
        raise OSError("injected output failure")

    monkeypatch.setattr(builtins, "print", fail_output)

    with pytest.raises(OSError, match="output failure"):
        task_tree.main(command_args(tree_path, command))

    assert not artifact.exists()
    data = load_tree(tree_path)
    if command == "prune-files":
        assert data["nodes"][0]["files_dir"] is None
    else:
        assert data["nodes"] == []


def test_partial_recursive_delete_is_retryable_with_scan_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    (artifact / "remaining.txt").write_text("retry", encoding="utf-8")
    real_rmtree = task_tree.shutil.rmtree

    def partial_cleanup(path):
        (Path(path) / "evidence.txt").unlink()
        raise OSError("injected partial rmtree")

    monkeypatch.setattr(task_tree.shutil, "rmtree", partial_cleanup)
    assert task_tree.main(command_args(tree_path, "prune-files")) == 1
    failed_payload = json.loads(capsys.readouterr().out)
    assert failed_payload["metadata_committed"] is True
    assert (artifact / "remaining.txt").is_file()
    assert load_tree(tree_path)["nodes"][0]["files_dir"] is None

    monkeypatch.setattr(task_tree.shutil, "rmtree", real_rmtree)
    assert task_tree.main(
        ["--tree-file", str(tree_path), "scan-files", "--prune", "--json"]
    ) == 0
    retry_payload = json.loads(capsys.readouterr().out)
    assert retry_payload["removed"] == [
        {"path": str(artifact), "task_id": 1}
    ]
    assert not artifact.exists()


@pytest.mark.parametrize("command", ["delete", "prune-files"])
def test_unmanaged_stored_path_is_detached_but_never_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    unmanaged = tmp_path / "outside" / "1"
    unmanaged.mkdir(parents=True)
    evidence = unmanaged / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")
    write_attached_tree(tree_path, files_dir=str(unmanaged))

    exit_code = task_tree.main(command_args(tree_path, command))

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"]["removed"] == []
    assert payload["cleanup"]["unmanaged"] == [
        {
            "kind": "task",
            "path": str(unmanaged),
            "task_id": 1,
            "reason": "files_dir is not the task's canonical managed path",
        }
    ]
    assert evidence.read_text(encoding="utf-8") == "keep"
    data = load_tree(tree_path)
    if command == "delete":
        assert data["nodes"] == []
    else:
        assert data["nodes"][0]["files_dir"] is None


def test_equivalent_spelling_with_symlink_and_parent_component_cannot_redirect_cleanup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    canonical = write_attached_tree(tree_path)
    external_parent = tmp_path / "external-parent"
    symlink_target = external_parent / "nested"
    redirected = external_parent / "files" / "1"
    symlink_target.mkdir(parents=True)
    redirected.mkdir(parents=True)
    evidence = redirected / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")
    (tmp_path / "alias").symlink_to(symlink_target, target_is_directory=True)
    data = load_tree(tree_path)
    data["nodes"][0]["files_dir"] = str(tmp_path / "alias" / ".." / "files" / "1")
    tree_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = task_tree.main(command_args(tree_path, "delete"))

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"]["removed"] == [
        {"kind": "task", "path": str(canonical), "task_id": 1}
    ]
    assert not canonical.exists()
    assert evidence.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize("command", ["delete", "prune-files"])
def test_symlinked_files_root_blocks_recursive_cleanup(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    tree_path = tmp_path / "tree.json"
    external = tmp_path / "external"
    artifact = external / "1"
    artifact.mkdir(parents=True)
    evidence = artifact / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")
    (tmp_path / "files").symlink_to(external, target_is_directory=True)
    data = {
        "schema_version": 2,
        "next_id": 2,
        "active_id": 1,
        "root_ids": [1],
        "nodes": [
            {
                "id": 1,
                "children": [],
                "summary": "Symlink root",
                "body": "",
                "status": "in_progress",
                "closeout_reviewed": False,
                "files_dir": str(tmp_path / "files" / "1"),
                "events": {},
            }
        ],
    }
    tree_path.write_text(json.dumps(data), encoding="utf-8")

    exit_code = task_tree.main(command_args(tree_path, command))

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert "non-symlink directory" in payload["cleanup"]["failed"][0]["error"]
    assert evidence.read_text(encoding="utf-8") == "keep"


def test_clear_prunes_canonical_directories_but_retains_suspicious_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    suspicious = tmp_path / "files" / "manual"
    suspicious.mkdir()
    evidence = suspicious / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")

    exit_code = task_tree.main(
        [
            "--tree-file",
            str(tree_path),
            "clear",
            "--prune-files",
            "--json",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"]["removed"] == [
        {"kind": "task", "path": str(artifact), "task_id": 1}
    ]
    assert payload["cleanup"]["unmanaged"] == [
        {
            "kind": "task-files",
            "path": str(suspicious),
            "reason": "directory name is not a canonical positive task ID",
        }
    ]
    assert evidence.read_text(encoding="utf-8") == "keep"


def test_clear_never_follows_a_shared_directory_symlink(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    write_attached_tree(tree_path)
    external = tmp_path / "external-shared"
    external.mkdir()
    evidence = external / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")
    (tmp_path / "shared").symlink_to(external, target_is_directory=True)

    exit_code = task_tree.main(
        [
            "--tree-file",
            str(tree_path),
            "clear",
            "--prune-shared",
            "--json",
        ]
    )

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["cleanup"]["failed"] == [
        {
            "kind": "shared",
            "path": str(tmp_path / "shared"),
            "error": "path is not a non-symlink directory",
        }
    ]
    assert evidence.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("command", "flags", "tree_exists", "files_exist", "shared_exists"),
    [
        ("clear", (), True, True, True),
        ("clear", ("--prune-files",), True, False, True),
        ("clear", ("--prune-shared",), True, True, False),
        (
            "clear",
            ("--prune-files", "--prune-shared", "--drop-file"),
            False,
            False,
            False,
        ),
        ("reset", (), True, False, True),
        ("reset", ("--prune-shared", "--drop-file"), False, False, False),
    ],
)
def test_clear_and_reset_flag_combinations(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    flags: tuple[str, ...],
    tree_exists: bool,
    files_exist: bool,
    shared_exists: bool,
) -> None:
    tree_path = tmp_path / "tree.json"
    attached = write_attached_tree(tree_path)
    orphan = tmp_path / "files" / "2"
    orphan.mkdir()
    (orphan / "orphan.txt").write_text("orphan", encoding="utf-8")
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "shared.txt").write_text("shared", encoding="utf-8")

    exit_code = task_tree.main(
        ["--tree-file", str(tree_path), command, *flags, "--json"]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == command
    assert payload["metadata_committed"] is True
    assert tree_path.exists() is tree_exists
    assert attached.exists() is files_exist
    assert orphan.exists() is files_exist
    assert shared.exists() is shared_exists
    if tree_exists:
        assert load_tree(tree_path)["nodes"] == []


def test_drop_file_failure_happens_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    before = tree_path.read_bytes()

    def fail_drop(_store):
        raise OSError("injected drop failure")

    monkeypatch.setattr(
        task_tree.TaskTreeStore, "remove_tree_file_unlocked", fail_drop
    )

    with pytest.raises(OSError, match="injected drop failure"):
        task_tree.main(
            [
                "--tree-file",
                str(tree_path),
                "clear",
                "--drop-file",
                "--prune-files",
                "--json",
            ]
        )

    assert capsys.readouterr().out == ""
    assert tree_path.read_bytes() == before
    assert (artifact / "evidence.txt").is_file()


def test_post_drop_error_leaves_artifacts_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    artifact = write_attached_tree(tree_path)
    real_drop = task_tree.TaskTreeStore.remove_tree_file_unlocked
    cleanup_started = False

    def drop_then_fail(store):
        real_drop(store)
        raise OSError("injected post-drop failure")

    def track_cleanup(_path):
        nonlocal cleanup_started
        cleanup_started = True

    monkeypatch.setattr(
        task_tree.TaskTreeStore, "remove_tree_file_unlocked", drop_then_fail
    )
    monkeypatch.setattr(task_tree.shutil, "rmtree", track_cleanup)

    with pytest.raises(OSError, match="post-drop failure"):
        task_tree.main(
            [
                "--tree-file",
                str(tree_path),
                "reset",
                "--drop-file",
                "--json",
            ]
        )

    assert capsys.readouterr().out == ""
    assert cleanup_started is False
    assert not tree_path.exists()
    assert (artifact / "evidence.txt").is_file()


def test_human_cleanup_failure_names_recovery_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    write_attached_tree(tree_path)

    def fail_cleanup(_path):
        raise OSError("injected cleanup failure")

    monkeypatch.setattr(task_tree.shutil, "rmtree", fail_cleanup)

    assert task_tree.main(
        ["--tree-file", str(tree_path), "prune-files", "1"]
    ) == 1

    output = capsys.readouterr().out
    assert "metadata committed; cleanup remains pending" in output
    assert "scan-files --prune" in output


def test_reset_holds_exclusive_lock_through_cleanup_before_id_reuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    tree_path = tmp_path / "tree.json"
    old_artifact = write_attached_tree(tree_path)
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()
    real_rmtree = task_tree.shutil.rmtree
    reset_result: list[int] = []

    def blocked_cleanup(path):
        cleanup_started.set()
        assert allow_cleanup.wait(timeout=5)
        return real_rmtree(path)

    monkeypatch.setattr(task_tree.shutil, "rmtree", blocked_cleanup)

    reset_thread = threading.Thread(
        target=lambda: reset_result.append(
            task_tree.main(["--tree-file", str(tree_path), "reset", "--json"])
        )
    )
    reset_thread.start()
    assert cleanup_started.wait(timeout=5)

    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    writer = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT),
            "--tree-file",
            str(tree_path),
            "add",
            "Reused ID",
            "--with-files",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(0.2)
    assert writer.poll() is None

    allow_cleanup.set()
    reset_thread.join(timeout=5)
    stdout, stderr = writer.communicate(timeout=5)

    assert reset_result == [0]
    assert writer.returncode == 0, stderr
    assert "Reused ID" in stdout
    assert load_tree(tree_path)["nodes"][0]["id"] == 1
    assert (tmp_path / "files" / "1").is_dir()
    assert not (tmp_path / "files" / "1" / "evidence.txt").exists()
    assert not old_artifact.joinpath("evidence.txt").exists()
    capsys.readouterr()
