import importlib.util
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"

spec = importlib.util.spec_from_file_location("task_tree_script", TASK_TREE)
task_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_tree)


def make_node(node_id, summary, status, parent_id=None, order=None, closeout_reviewed=False):
    return {
        "id": node_id,
        "_parent_id": parent_id,
        "_order": order if order is not None else node_id,
        "children": [],
        "summary": summary,
        "body": "",
        "status": status,
        "closeout_reviewed": closeout_reviewed,
        "files_dir": None,
        "events": {},
    }


def make_data(nodes, active_id=None):
    grouped = {}
    for node in nodes:
        grouped.setdefault(node.pop("_parent_id"), []).append(node)
    for siblings in grouped.values():
        siblings.sort(key=lambda item: (item.pop("_order"), item["id"]))
    for parent_id, children in grouped.items():
        if parent_id is not None:
            next(node for node in nodes if node["id"] == parent_id)["children"] = [
                child["id"] for child in children
            ]
    return {
        "schema_version": 2,
        "next_id": max(n["id"] for n in nodes) + 1,
        "active_id": active_id,
        "root_ids": [node["id"] for node in grouped.get(None, [])],
        "nodes": nodes,
    }


def chosen_id(data):
    node = task_tree.choose_next_task(data)
    return None if node is None else node["id"]


def chosen_id_relative(data, node_id):
    node = task_tree.choose_next_task(data, relative_to_id=node_id)
    return None if node is None else node["id"]


class TaskTreeNextSelectionTest(unittest.TestCase):
    def test_active_parent_searches_pending_children_first(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Done child", "completed", parent_id=1),
                make_node(3, "Pending child", "not_started", parent_id=1),
                make_node(4, "Other root", "not_started"),
            ],
            active_id=1,
        )

        self.assertEqual(chosen_id(data), 3)

    def test_completed_active_leaf_returns_parent_for_closeout_when_children_done(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Parent needing closeout", "in_progress", parent_id=1),
                make_node(3, "Last child", "completed", parent_id=2),
            ],
            active_id=3,
        )

        self.assertEqual(chosen_id(data), 2)

    def test_completed_active_leaf_returns_next_child_before_parent_closeout(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Parent", "in_progress", parent_id=1),
                make_node(3, "Done child", "completed", parent_id=2),
                make_node(4, "Next child", "not_started", parent_id=2),
            ],
            active_id=3,
        )

        self.assertEqual(chosen_id(data), 4)

    def test_completed_active_leaf_under_completed_parent_continues_after_parent_branch(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Completed parent", "completed", parent_id=1),
                make_node(3, "Done child", "completed", parent_id=2),
                make_node(4, "Later sibling", "not_started", parent_id=1),
            ],
            active_id=3,
        )

        self.assertEqual(chosen_id(data), 4)

    def test_completed_active_rightmost_branch_does_not_wrap_to_earlier_root(self):
        data = make_data(
            [
                make_node(1, "Earlier root", "in_progress", order=1),
                make_node(2, "Completed later root", "completed", order=2),
                make_node(3, "Done child", "completed", parent_id=2),
            ],
            active_id=3,
        )

        self.assertIsNone(task_tree.choose_next_task(data))

    def test_next_can_be_calculated_relative_to_supplied_task_id(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Parent", "in_progress", parent_id=1),
                make_node(3, "Done child", "completed", parent_id=2),
                make_node(4, "Next child", "not_started", parent_id=2),
                make_node(5, "Active elsewhere", "in_progress"),
            ],
            active_id=5,
        )

        self.assertEqual(chosen_id(data), 5)
        self.assertEqual(chosen_id_relative(data, 3), 4)
        self.assertEqual(data["active_id"], 5)

    def test_relative_next_returns_parent_for_closeout_before_parent_later_siblings(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Earlier sibling", "not_started", parent_id=1),
                make_node(3, "Parent", "in_progress", parent_id=1),
                make_node(4, "Done child", "completed", parent_id=3),
                make_node(5, "Later sibling", "not_started", parent_id=1),
            ],
            active_id=3,
        )

        self.assertEqual(chosen_id_relative(data, 4), 3)

    def test_closeout_reviewed_suppresses_closeout_due(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Parent", "in_progress", parent_id=1, closeout_reviewed=True),
                make_node(3, "Done child", "completed", parent_id=2),
                make_node(4, "Later sibling", "not_started", parent_id=1),
            ],
            active_id=2,
        )

        self.assertFalse(task_tree.closeout_review_due(data, data["nodes"][1]))

    def test_relative_next_returns_parent_for_closeout_before_parent_earlier_siblings(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Earlier sibling", "not_started", parent_id=1),
                make_node(3, "Parent", "in_progress", parent_id=1),
                make_node(4, "Done child", "completed", parent_id=3),
            ],
            active_id=3,
        )

        self.assertEqual(chosen_id_relative(data, 4), 3)

    def test_relative_next_returns_parent_only_after_sibling_search_exhausted(self):
        data = make_data(
            [
                make_node(1, "Root", "in_progress"),
                make_node(2, "Parent", "in_progress", parent_id=1),
                make_node(3, "Done child", "completed", parent_id=2),
            ],
            active_id=2,
        )

        self.assertEqual(chosen_id_relative(data, 3), 2)


if __name__ == "__main__":
    unittest.main()
