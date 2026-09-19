import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"
FIXTURE = TEST_DIR / "fixtures" / "current_task_tree_example" / "tree.json"


def copy_fixture(tmp_path: Path) -> Path:
    output = tmp_path / "tree.json"
    shutil.copy2(FIXTURE, output)
    return output


def run_tree(tree: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TASK_TREE_FILE"] = str(tree)
    return subprocess.run(
        [sys.executable, str(TASK_TREE), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def load(tree: Path):
    return json.loads(tree.read_text(encoding="utf-8"))


def node(data, node_id):
    return next(item for item in data["nodes"] if item["id"] == node_id)


def assert_relationships_are_parent_owned(data):
    assert data["schema_version"] == 2
    assert all("parent_id" not in item for item in data["nodes"])
    assert all("sibling_order" not in item for item in data["nodes"])


def test_add_appends_to_parent_owned_list_without_legacy_fields(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "add", "New child", "--parent", "1")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 5, 4, 7, 9, 10]
    assert node(data, 10)["children"] == []
    assert_relationships_are_parent_owned(data)


def test_add_root_appends_to_root_ids(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "add", "New root")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert data["root_ids"] == [2, 1, 10]
    assert_relationships_are_parent_owned(data)


def test_insert_before_active_requires_reorder_and_focus_transfer(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    assert run_tree(tree, "add", "Urgent prerequisite", "--parent", "1").returncode == 0
    assert run_tree(tree, "reorder", "10", "--before", "4").returncode == 0
    assert run_tree(tree, "set-active", "10").returncode == 0

    data = load(tree)
    assert node(data, 1)["children"] == [3, 5, 10, 4, 7, 9]
    assert data["active_id"] == 10
    assert_relationships_are_parent_owned(data)

    completed = run_tree(tree, "update", "10", "--status", "completed")
    assert completed.returncode == 0, completed.stderr
    resumed = load(tree)
    assert resumed["active_id"] == 4
    assert node(resumed, 1)["children"] == [3, 5, 10, 4, 7, 9]


def test_reorder_mutates_only_authoritative_owner_list(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "reorder", "5", "--after", "4")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 4, 5, 7, 9]
    assert_relationships_are_parent_owned(data)


def test_move_removes_old_membership_and_appends_to_new_parent(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "move", "5", "--parent", "4")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 4, 7, 9]
    assert node(data, 4)["children"] == [6, 5]
    assert_relationships_are_parent_owned(data)


def test_move_within_same_parent_places_task_last(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "move", "5", "--parent", "1")

    assert result.returncode == 0, result.stderr
    assert node(load(tree), 1)["children"] == [3, 4, 7, 9, 5]


def test_move_rejects_cycle_without_changing_tree(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    before = tree.read_text(encoding="utf-8")

    result = run_tree(tree, "move", "1", "--parent", "6")

    assert result.returncode == 2
    assert "own subtree" in result.stderr
    assert tree.read_text(encoding="utf-8") == before


def test_delete_leaf_removes_parent_owned_membership(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "delete", "5")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 4, 7, 9]
    assert all(item["id"] != 5 for item in data["nodes"])
    assert_relationships_are_parent_owned(data)


def test_force_delete_removes_complete_subtree_and_membership(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "delete", "7", "--force")

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 5, 4, 9]
    assert {item["id"] for item in data["nodes"]}.isdisjoint({7, 8})
    assert_relationships_are_parent_owned(data)


def test_reset_writes_empty_valid_v2_store(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "reset")

    assert result.returncode == 0, result.stderr
    assert load(tree) == {
        "active_id": None,
        "next_id": 1,
        "nodes": [],
        "root_ids": [],
        "schema_version": 2,
    }
