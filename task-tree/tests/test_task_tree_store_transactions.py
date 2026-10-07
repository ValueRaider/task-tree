import importlib.util
import json
import os
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"

spec = importlib.util.spec_from_file_location("task_tree_store_transactions", TASK_TREE)
task_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_tree)


def populated_tree(summary="Committed"):
    return {
        "schema_version": 2,
        "next_id": 2,
        "active_id": None,
        "root_ids": [1],
        "nodes": [
            {
                "id": 1,
                "children": [],
                "summary": summary,
                "body": "",
                "status": "not_started",
                "closeout_reviewed": False,
                "files_dir": None,
                "events": {},
            }
        ],
    }


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_explicit_transaction_commits_once_without_an_exit_write(tmp_path):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    cleanup_target = tmp_path / "cleanup-target"
    cleanup_target.write_text("remove after commit", encoding="utf-8")
    writes = []
    real_write = store._write_unlocked

    def tracked_write(data):
        writes.append(json.loads(json.dumps(data)))
        real_write(data)

    store._write_unlocked = tracked_write

    with store.locked_transaction() as transaction:
        transaction.data.clear()
        transaction.data.update(populated_tree())
        transaction.commit()
        cleanup_target.unlink()
        transaction.data["nodes"][0]["summary"] = "Changed after commit"
        with pytest.raises(RuntimeError, match="already has a commit point"):
            transaction.commit()

    assert len(writes) == 1
    assert load(path)["nodes"][0]["summary"] == "Committed"
    assert not cleanup_target.exists()


def test_explicit_transaction_without_commit_leaves_tree_unchanged(tmp_path):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    store._write_unlocked(populated_tree("Before"))
    before = path.read_bytes()

    with store.locked_transaction() as transaction:
        transaction.data["nodes"][0]["summary"] = "Not committed"

    assert path.read_bytes() == before


def test_failed_commit_prevents_following_cleanup_and_cannot_be_retried(tmp_path):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    store._write_unlocked(populated_tree("Before"))
    before = path.read_bytes()
    artifact = tmp_path / "files" / "1" / "evidence.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("keep", encoding="utf-8")

    def fail_write(_data):
        raise OSError("injected tree write failure")

    store._write_unlocked = fail_write

    with pytest.raises(OSError, match="injected"):
        with store.locked_transaction() as transaction:
            transaction.data["nodes"][0]["summary"] = "After"
            try:
                transaction.commit()
            except OSError:
                assert transaction.finalized is True
                with pytest.raises(RuntimeError, match="already has a commit point"):
                    transaction.commit()
                raise
            # Tree-first destructive callers put cleanup here, so a failed
            # commit exits before this path is touched.
            artifact.unlink()

    assert path.read_bytes() == before
    assert artifact.read_text(encoding="utf-8") == "keep"


def test_tree_replace_syncs_file_then_replaces_then_syncs_directory(
    tmp_path, monkeypatch
):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    events = []
    real_fsync = os.fsync
    real_replace = os.replace

    def tracked_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def tracked_replace(source, destination):
        events.append("replace")
        return real_replace(source, destination)

    monkeypatch.setattr(task_tree.os, "fsync", tracked_fsync)
    monkeypatch.setattr(task_tree.os, "replace", tracked_replace)

    store._write_unlocked(populated_tree())

    assert events == ["fsync", "replace", "fsync"]
    assert load(path) == populated_tree()


def test_failed_replace_keeps_old_valid_tree_and_removes_temp_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    store._write_unlocked(populated_tree("Before"))
    before = path.read_bytes()

    def fail_replace(_source, _destination):
        raise OSError("injected replace failure")

    monkeypatch.setattr(task_tree.os, "replace", fail_replace)

    with pytest.raises(OSError, match="injected"):
        store._write_unlocked(populated_tree("After"))

    assert path.read_bytes() == before
    assert load(path)["nodes"][0]["summary"] == "Before"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["tree.json"]


def test_error_after_replace_leaves_new_valid_tree_without_temp_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    store._write_unlocked(populated_tree("Before"))
    real_replace = os.replace

    def replace_then_fail(source, destination):
        real_replace(source, destination)
        raise OSError("injected post-replace failure")

    monkeypatch.setattr(task_tree.os, "replace", replace_then_fail)

    with pytest.raises(OSError, match="post-replace"):
        store._write_unlocked(populated_tree("After"))

    assert load(path)["nodes"][0]["summary"] == "After"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["tree.json"]


def test_tree_removal_syncs_parent_directory(tmp_path, monkeypatch):
    path = tmp_path / "tree.json"
    store = task_tree.TaskTreeStore(str(path))
    store._write_unlocked(populated_tree())
    events = []
    real_remove = os.remove
    real_fsync = os.fsync

    def tracked_remove(target):
        events.append("remove")
        return real_remove(target)

    def tracked_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(task_tree.os, "remove", tracked_remove)
    monkeypatch.setattr(task_tree.os, "fsync", tracked_fsync)

    assert store.remove_tree_file_unlocked() is True

    assert events == ["remove", "fsync"]
    assert not path.exists()


def test_clear_can_replace_a_structurally_invalid_tree(tmp_path, capsys):
    path = tmp_path / "tree.json"
    invalid = populated_tree()
    invalid["root_ids"] = []
    path.write_text(json.dumps(invalid), encoding="utf-8")

    assert task_tree.main(["--tree-file", str(path), "clear"]) == 0

    assert load(path) == task_tree.TaskTreeStore(str(path))._empty_data()
    assert capsys.readouterr().out == (
        "(empty tree)\n"
        "cleanup: requested=0 removed=0 absent=0 unmanaged=0 failed=0\n"
    )


def test_mutation_command_emits_nothing_when_commit_fails(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "tree.json"

    def fail_write(_store, _data):
        raise OSError("injected commit failure")

    monkeypatch.setattr(task_tree.TaskTreeStore, "_write_unlocked", fail_write)

    with pytest.raises(OSError, match="injected"):
        task_tree.main(["--tree-file", str(path), "add", "No false success"])

    captured = capsys.readouterr()
    assert captured.out == ""
    assert not path.exists()
