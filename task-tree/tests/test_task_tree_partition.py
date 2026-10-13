import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"
FIXTURE = TEST_DIR / "fixtures" / "current_task_tree_example" / "tree.json"


def copy_fixture(tmp_path: Path) -> Path:
    tree = tmp_path / "tree.json"
    shutil.copy2(FIXTURE, tree)
    return tree


def write_spec(tmp_path: Path, payload) -> Path:
    spec = tmp_path / "inputs" / "partition.json"
    spec.parent.mkdir()
    spec.write_text(json.dumps(payload), encoding="utf-8")
    return spec


def run_tree(tree: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("TASK_TREE_FILE", None)
    return subprocess.run(
        [sys.executable, str(TASK_TREE), "--tree-dir", str(tree.parent), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def load(tree: Path):
    return json.loads(tree.read_text(encoding="utf-8"))


def node(data, node_id):
    return next(item for item in data["nodes"] if item["id"] == node_id)


def valid_payload():
    return {
        "schema_version": 1,
        "steps": [
            {"summary": "First supplied step ", "body": "First supplied body "},
            {"summary": "Second supplied step", "body": "Second supplied body"},
        ],
    }


def test_partition_appends_ordered_children_with_standard_lifecycle_events(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, valid_payload())

    result = run_tree(tree, "partition", "1", "--from-file", str(spec))

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert node(data, 1)["children"] == [3, 5, 4, 7, 9, 10, 11]
    assert data["next_id"] == 12
    for node_id, supplied in ((10, valid_payload()["steps"][0]), (11, valid_payload()["steps"][1])):
        created = node(data, node_id)
        assert created["summary"] == supplied["summary"]
        assert created["body"] == supplied["body"]
        assert created["status"] == "not_started"
        assert created["children"] == []
        assert created["files_dir"] is None
        assert created["closeout_reviewed"] is False
        assert set(created["events"]) == {
            "created_at",
            "status_changed_at",
            "body_updated_at",
            "last_mutated_at",
        }
        assert len({created["events"][event] for event in created["events"]}) == 1
    assert not (tmp_path / "files").exists()


def test_partition_set_active_first_activates_only_first_new_child(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, valid_payload())

    result = run_tree(
        tree,
        "partition",
        "1",
        "--from-file",
        str(spec),
        "--set-active-first",
    )

    assert result.returncode == 0, result.stderr
    data = load(tree)
    assert data["active_id"] == 10
    assert "activated_at" in node(data, 10)["events"]
    assert "activated_at" not in node(data, 11)["events"]


def test_partition_invalidates_parent_closeout_review(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    data = load(tree)
    node(data, 1)["closeout_reviewed"] = True
    tree.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    spec = write_spec(tmp_path, valid_payload())

    result = run_tree(tree, "partition", "1", "--from-file", str(spec))

    assert result.returncode == 0, result.stderr
    updated = load(tree)
    parent = node(updated, 1)
    first_child = node(updated, 10)
    assert parent["closeout_reviewed"] is False
    assert parent["events"]["closeout_reviewed_updated_at"] == first_child["events"]["created_at"]


def test_partition_uses_explicit_global_tree_file(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, valid_payload())

    result = run_tree(tree, "partition", "1", "--from-file", str(spec))

    assert result.returncode == 0, result.stderr
    assert [item["id"] for item in load(tree)["nodes"]] == list(range(1, 12))


def assert_failed_without_mutation(tree: Path, spec: Path, *args: str):
    before = tree.read_bytes()
    result = run_tree(tree, "partition", *args, "--from-file", str(spec))
    assert result.returncode == 2
    assert result.stderr.startswith("error: ")
    assert tree.read_bytes() == before
    return result


def test_invalid_json_leaves_tree_bytes_unchanged(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = tmp_path / "invalid.json"
    spec.write_text("{\"schema_version\": 1,", encoding="utf-8")

    result = assert_failed_without_mutation(tree, spec, "1")

    assert "invalid partition JSON" in result.stderr


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"schema_version": 1},
        {"steps": []},
        {"schema_version": 1, "steps": [], "extra": "rejected"},
        {"schema_version": 2, "steps": []},
        {"schema_version": True, "steps": []},
        {"schema_version": 1, "steps": None},
        {"schema_version": 1, "steps": {}},
        {"schema_version": 1, "steps": [None]},
        {"schema_version": 1, "steps": [{}]},
        {"schema_version": 1, "steps": [{"summary": "only summary"}]},
        {
            "schema_version": 1,
            "steps": [{"summary": "summary", "body": "body", "extra": 1}],
        },
        {"schema_version": 1, "steps": [{"summary": 1, "body": "body"}]},
        {"schema_version": 1, "steps": [{"summary": "summary", "body": None}]},
        {"schema_version": 1, "steps": [{"summary": " \t", "body": "body"}]},
        {"schema_version": 1, "steps": [{"summary": "summary", "body": "\n"}]},
    ],
)
def test_invalid_partition_shapes_leave_tree_bytes_unchanged(tmp_path: Path, payload):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, payload)

    assert_failed_without_mutation(tree, spec, "1")


def test_invalid_second_step_does_not_persist_first_step(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(
        tmp_path,
        {
            "schema_version": 1,
            "steps": [
                {"summary": "Would be first", "body": "Would be persisted"},
                {"summary": "", "body": "Invalid second step"},
            ],
        },
    )

    assert_failed_without_mutation(tree, spec, "1")


def test_missing_parent_leaves_tree_bytes_unchanged(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, valid_payload())

    result = assert_failed_without_mutation(tree, spec, "999")

    assert "Node 999 does not exist" in result.stderr


def test_partition_help_exposes_command_and_flags(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(TASK_TREE), "--help"],
        text=True,
        capture_output=True,
        check=False,
        env=dict(os.environ),
    )

    assert result.returncode == 0, result.stderr
    assert "partition <parent-id>" in result.stdout
    assert "--from-file PATH" in result.stdout
    assert "--set-active-first" in result.stdout
    assert "--full-tree" in result.stdout


def test_partition_supports_standard_full_tree_output(tmp_path: Path):
    tree = copy_fixture(tmp_path)
    spec = write_spec(tmp_path, valid_payload())

    result = run_tree(tree, "partition", "1", "--from-file", str(spec), "--full-tree")

    assert result.returncode == 0, result.stderr
    assert "#10 First supplied step" in result.stdout
    assert "#11 Second supplied step" in result.stdout
