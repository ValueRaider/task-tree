import copy
import json
import sys
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE = TEST_DIR / "fixtures" / "v1_migration_example" / "legacy-tree.json"

sys.path.insert(0, str(SCRIPTS_DIR))
from task_tree_schema import (
    TaskTreeMigrationRequired,
    TaskTreeSchemaError,
    initialize_missing_schema_version,
    validate_tree,
)


def node(
    node_id,
    *,
    children=None,
    status="not_started",
):
    return {
        "id": node_id,
        "children": list(children or []),
        "summary": f"Task {node_id}",
        "body": "",
        "status": status,
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def current_tree():
    return {
        "schema_version": 2,
        "next_id": 3,
        "active_id": 2,
        "root_ids": [1],
        "nodes": [node(1, children=[2], status="in_progress"), node(2)],
    }


def legacy_tree():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_accepts_current_and_empty_current_trees():
    validate_tree(current_tree())
    validate_tree(
        {
            "schema_version": 2,
            "next_id": 1,
            "active_id": None,
            "root_ids": [],
            "nodes": [],
        }
    )


def test_initializes_missing_version_only_for_populated_current_shape():
    data = current_tree()
    data.pop("schema_version")

    assert initialize_missing_schema_version(data) is True
    assert data["schema_version"] == 2
    validate_tree(data)


@pytest.mark.parametrize(
    "data",
    [
        {
            "next_id": 1,
            "active_id": None,
            "root_ids": [],
            "nodes": [],
        },
        legacy_tree(),
        {
            "next_id": 2,
            "active_id": 1,
            "root_ids": [1],
            "nodes": [
                {
                    **node(1),
                    "parent_id": None,
                }
            ],
        },
    ],
)
def test_does_not_initialize_empty_legacy_or_mixed_relationship_shapes(data):
    data.pop("schema_version", None)

    assert initialize_missing_schema_version(data) is False
    assert "schema_version" not in data


@pytest.mark.parametrize(
    "data",
    [
        legacy_tree(),
        {
            "next_id": 1,
            "active_id": None,
            "nodes": [],
        },
        {
            "schema_version": 1,
            "next_id": 1,
            "active_id": None,
            "nodes": [],
        },
    ],
)
def test_recognizable_legacy_input_requires_manual_migration(data):
    with pytest.raises(TaskTreeMigrationRequired, match="manual migration utility"):
        validate_tree(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data.pop("schema_version"), "missing required schema_version"),
        (
            lambda data: data.update(schema_version=1),
            "current relationship structure conflicts",
        ),
        (
            lambda data: data["nodes"][0].update(parent_id=None),
            "mixed or incomplete relationship structure",
        ),
        (
            lambda data: data["nodes"][0].pop("children"),
            "mixed or incomplete relationship structure",
        ),
        (lambda data: data.update(root_ids="1"), "root_ids must be a list"),
    ],
)
def test_rejects_missing_conflicting_or_mixed_format_markers(mutate, message):
    data = current_tree()
    mutate(data)
    with pytest.raises(TaskTreeSchemaError, match=message):
        validate_tree(data)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda data: data["nodes"].append(copy.deepcopy(data["nodes"][0])),
            "duplicate node id",
        ),
        (lambda data: data.update(next_id=2), "next_id must be greater"),
        (
            lambda data: data["nodes"][1].update(status="unknown"),
            "invalid status",
        ),
        (
            lambda data: data["nodes"][1].pop("summary"),
            "missing required field summary",
        ),
        (
            lambda data: data["nodes"][0]["children"].append(2),
            "multiple owning positions",
        ),
        (
            lambda data: data["nodes"][0]["children"].append(99),
            "references missing node 99",
        ),
    ],
)
def test_rejects_invalid_payloads_and_ownership(mutate, message):
    data = current_tree()
    mutate(data)
    with pytest.raises(TaskTreeSchemaError, match=message):
        validate_tree(data)


def test_detects_cycle_even_when_disconnected_from_roots():
    data = current_tree()
    data["root_ids"] = []
    data["nodes"][1]["children"] = [1]

    with pytest.raises(TaskTreeSchemaError, match="cycle detected"):
        validate_tree(data)


@pytest.mark.parametrize("invalid_active", [99, "2"])
def test_active_validation_can_be_skipped_without_skipping_structure(invalid_active):
    data = current_tree()
    data["active_id"] = invalid_active

    with pytest.raises(TaskTreeSchemaError, match="active_id"):
        validate_tree(data)
    validate_tree(data, validate_active=False)

    data["root_ids"] = []
    with pytest.raises(TaskTreeSchemaError, match="owning position"):
        validate_tree(data, validate_active=False)


def test_terminal_task_can_remain_active_as_return_focus():
    data = current_tree()
    data["nodes"][1]["status"] = "completed"

    validate_tree(data)


def test_return_to_reference_must_exist_and_leave_own_subtree():
    data = current_tree()
    data["nodes"][1]["return_to_id"] = 1
    validate_tree(data)

    data["nodes"][1]["return_to_id"] = 99
    with pytest.raises(TaskTreeSchemaError, match="references missing node 99"):
        validate_tree(data)

    data = current_tree()
    data["nodes"][0]["return_to_id"] = 2
    with pytest.raises(TaskTreeSchemaError, match="own descendant 2"):
        validate_tree(data)

    data["nodes"][0]["return_to_id"] = 1
    with pytest.raises(TaskTreeSchemaError, match="return to itself"):
        validate_tree(data)
