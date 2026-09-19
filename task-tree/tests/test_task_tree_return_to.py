import json
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT = TEST_DIR.parent / "scripts" / "task_tree.py"


def run_tree(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tree-file",
            str(tmp_path / "tree.json"),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def load_tree(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "tree.json").read_text(encoding="utf-8"))


def task(data: dict, node_id: int) -> dict:
    return next(node for node in data["nodes"] if node["id"] == node_id)


def test_return_override_beats_normal_tree_order(tmp_path):
    assert run_tree(tmp_path, "add", "Work to resume", "--set-active").returncode == 0
    assert run_tree(tmp_path, "add", "Ordinary next task").returncode == 0
    added = run_tree(
        tmp_path,
        "add",
        "Urgent interruption",
        "--return-to",
        "1",
        "--set-active",
    )
    assert added.returncode == 0, added.stderr

    completed = run_tree(tmp_path, "update", "3", "--status", "completed")

    assert completed.returncode == 0, completed.stderr
    data = load_tree(tmp_path)
    assert data["active_id"] == 1
    assert task(data, 3)["return_to_id"] == 1
    assert "active:\n  id: 1\n  summary: Work to resume" in completed.stdout


def test_return_can_focus_terminal_target_but_direct_set_active_cannot(tmp_path):
    assert run_tree(tmp_path, "add", "Finished origin", "--set-active").returncode == 0
    assert run_tree(tmp_path, "update", "1", "--status", "completed").returncode == 0
    assert run_tree(
        tmp_path,
        "add",
        "Urgent interruption",
        "--return-to",
        "1",
        "--set-active",
    ).returncode == 0

    completed = run_tree(tmp_path, "update", "2", "--status", "completed")

    assert completed.returncode == 0, completed.stderr
    assert load_tree(tmp_path)["active_id"] == 1
    assert "status: completed" in completed.stdout
    rejected = run_tree(tmp_path, "set-active", "1")
    assert rejected.returncode == 2
    assert "Cannot set completed task active" in rejected.stderr


def test_parent_return_waits_until_its_pending_descendant_finishes(tmp_path):
    assert run_tree(tmp_path, "add", "Work to resume").returncode == 0
    assert run_tree(
        tmp_path,
        "add",
        "Priority branch",
        "--return-to",
        "1",
        "--set-active",
    ).returncode == 0
    assert run_tree(
        tmp_path,
        "add",
        "Priority child",
        "--parent",
        "2",
        "--set-active",
    ).returncode == 0

    parent_completed = run_tree(tmp_path, "update", "2", "--status", "completed")
    assert parent_completed.returncode == 0, parent_completed.stderr
    assert load_tree(tmp_path)["active_id"] == 3

    child_completed = run_tree(tmp_path, "update", "3", "--status", "completed")
    assert child_completed.returncode == 0, child_completed.stderr
    assert load_tree(tmp_path)["active_id"] == 1


def test_return_edge_is_visible_and_can_be_cleared(tmp_path):
    assert run_tree(tmp_path, "add", "Origin").returncode == 0
    assert run_tree(
        tmp_path, "add", "Interruption", "--return-to", "1"
    ).returncode == 0

    details = run_tree(tmp_path, "show", "2", "--details")
    assert details.returncode == 0, details.stderr
    assert "return_to_id: [ ] #1 Origin" in details.stdout

    as_json = run_tree(tmp_path, "show", "2", "--json")
    assert as_json.returncode == 0, as_json.stderr
    assert json.loads(as_json.stdout)["return_to_id"] == 1

    cleared = run_tree(tmp_path, "update", "2", "--clear-return-to")
    assert cleared.returncode == 0, cleared.stderr
    assert "return_to_id" not in task(load_tree(tmp_path), 2)


def test_return_edge_rejects_self_descendant_and_missing_targets(tmp_path):
    assert run_tree(tmp_path, "add", "Parent").returncode == 0
    assert run_tree(tmp_path, "add", "Child", "--parent", "1").returncode == 0

    cases = (
        (("update", "1", "--return-to", "1"), "cannot return to itself"),
        (("update", "1", "--return-to", "2"), "own descendant"),
        (("update", "2", "--return-to", "99"), "does not exist"),
    )
    before = (tmp_path / "tree.json").read_text(encoding="utf-8")
    for command, message in cases:
        result = run_tree(tmp_path, *command)
        assert result.returncode == 2
        assert message in result.stderr
        assert (tmp_path / "tree.json").read_text(encoding="utf-8") == before


def test_delete_refuses_to_remove_a_surviving_return_target(tmp_path):
    assert run_tree(tmp_path, "add", "Origin").returncode == 0
    assert run_tree(
        tmp_path, "add", "Interruption", "--return-to", "1"
    ).returncode == 0

    rejected = run_tree(tmp_path, "delete", "1")
    assert rejected.returncode == 2
    assert "clear or rewrite return_to_id on task(s): 2" in rejected.stderr
    assert {node["id"] for node in load_tree(tmp_path)["nodes"]} == {1, 2}

    forced = run_tree(tmp_path, "delete", "1", "--force")
    assert forced.returncode == 2
    assert "clear or rewrite return_to_id on task(s): 2" in forced.stderr

    assert run_tree(tmp_path, "update", "2", "--clear-return-to").returncode == 0
    deleted = run_tree(tmp_path, "delete", "1")
    assert deleted.returncode == 0, deleted.stderr


def test_delete_allows_subtree_when_source_and_target_are_both_removed(tmp_path):
    assert run_tree(tmp_path, "add", "Origin").returncode == 0
    assert run_tree(
        tmp_path,
        "add",
        "Nested interruption",
        "--parent",
        "1",
        "--return-to",
        "1",
    ).returncode == 0

    deleted = run_tree(tmp_path, "delete", "1", "--force")

    assert deleted.returncode == 0, deleted.stderr
    assert load_tree(tmp_path)["nodes"] == []
