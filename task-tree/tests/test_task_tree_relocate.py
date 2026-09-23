import copy
import importlib.util
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_tree.py"
spec = importlib.util.spec_from_file_location("task_tree_relocate", SCRIPT)
task_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_tree)


def make_node(node_id, children=(), *, closeout_reviewed=False):
    return {
        "id": node_id,
        "children": list(children),
        "summary": f"Task {node_id}",
        "body": "",
        "status": "in_progress",
        "closeout_reviewed": closeout_reviewed,
        "files_dir": None,
        "events": {},
    }


def make_tree():
    nodes = [
        make_node(1, [2, 3], closeout_reviewed=True),
        make_node(2, [7]),
        make_node(3),
        make_node(4, [5, 6], closeout_reviewed=True),
        make_node(5),
        make_node(6),
        make_node(7),
    ]
    return {
        "schema_version": 2,
        "next_id": 8,
        "active_id": None,
        "root_ids": [1, 4],
        "nodes": nodes,
    }


def node(data, node_id):
    return next(item for item in data["nodes"] if item["id"] == node_id)


def test_cross_parent_before_anchor_returns_complete_receipt_and_shared_timestamp():
    data = make_tree()

    receipt = task_tree.relocate_node(data, 2, 4, before_id=6)

    assert node(data, 1)["children"] == [3]
    assert node(data, 4)["children"] == [5, 2, 6]
    assert node(data, 2)["children"] == [7]
    assert receipt == task_tree.RelocationReceipt(
        source_id=2,
        original_parent_id=1,
        original_index=0,
        original_previous_id=None,
        original_next_id=3,
        destination_parent_id=4,
        final_index=1,
        final_previous_id=5,
        final_next_id=6,
        moved_at=receipt.moved_at,
    )
    assert node(data, 2)["events"]["moved_at"] == receipt.moved_at
    assert node(data, 1)["closeout_reviewed"] is False
    assert node(data, 4)["closeout_reviewed"] is False
    assert node(data, 1)["events"]["closeout_reviewed_updated_at"] == receipt.moved_at
    assert node(data, 4)["events"]["closeout_reviewed_updated_at"] == receipt.moved_at
    with pytest.raises(FrozenInstanceError):
        receipt.final_index = 0


def test_same_parent_after_anchor_uses_post_removal_index():
    data = make_tree()

    receipt = task_tree.relocate_node(data, 2, 1, after_id=3)

    assert node(data, 1)["children"] == [3, 2]
    assert receipt.original_index == 0
    assert receipt.final_index == 1
    assert receipt.original_previous_id is None
    assert receipt.original_next_id == 3
    assert receipt.final_previous_id == 3
    assert receipt.final_next_id is None


def test_relocation_without_anchor_appends_to_destination():
    data = make_tree()

    receipt = task_tree.relocate_node(data, 3, 4)

    assert node(data, 1)["children"] == [2]
    assert node(data, 4)["children"] == [5, 6, 3]
    assert receipt.final_index == 2
    assert receipt.final_previous_id == 6
    assert receipt.final_next_id is None


def test_cycle_rejection_leaves_data_unchanged():
    data = make_tree()
    before = copy.deepcopy(data)

    with pytest.raises(ValueError, match="own subtree"):
        task_tree.relocate_node(data, 1, 7)

    assert data == before


def test_anchor_must_be_owned_by_destination_parent():
    data = make_tree()
    before = copy.deepcopy(data)

    with pytest.raises(ValueError, match="not a sibling"):
        task_tree.relocate_node(data, 2, 4, before_id=3)

    assert data == before
