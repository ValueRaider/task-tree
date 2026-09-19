import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
REPO_ROOT = SKILL_DIR.parents[2]
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"

spec = importlib.util.spec_from_file_location("task_tree_script", TASK_TREE)
task_tree = importlib.util.module_from_spec(spec)
spec.loader.exec_module(task_tree)


def run_tree(tmp_dir, *args):
    env = os.environ.copy()
    env["TASK_TREE_FILE"] = str(Path(tmp_dir) / "tree.json")
    result = subprocess.run(
        [sys.executable, str(TASK_TREE), *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout


class TaskTreeReorderTest(unittest.TestCase):


    def test_invalid_active_id_makes_normal_commands_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "not_started")
            tree_file = Path(tmp_dir) / "tree.json"
            data = json.loads(tree_file.read_text())
            data["active_id"] = 999
            tree_file.write_text(json.dumps(data))

            env = os.environ.copy()
            env["TASK_TREE_FILE"] = str(tree_file)
            result = subprocess.run(
                [sys.executable, str(TASK_TREE), "active"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("active_id references missing node 999", result.stderr)

    def test_clear_active_recovers_invalid_active_id(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "not_started")
            tree_file = Path(tmp_dir) / "tree.json"
            data = json.loads(tree_file.read_text())
            data["active_id"] = 999
            tree_file.write_text(json.dumps(data))

            out = run_tree(tmp_dir, "clear-active")
            active = run_tree(tmp_dir, "active")

            self.assertIn("[ ] #1 Root", out)
            self.assertIn("(no active task)", active)

    def test_write_rejects_invalid_active_id_after_mutation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = task_tree.TaskTreeStore(str(Path(tmp_dir) / "tree.json"))
            with store.locked_data(write=True) as data:
                data["nodes"].append(
                    {
                        "id": 1,
                        "children": [],
                        "summary": "Root",
                        "body": "",
                        "status": "not_started",
                        "closeout_reviewed": False,
                        "files_dir": None,
                        "events": {},
                    }
                )
                data["root_ids"].append(1)
                data["next_id"] = 2
                data["active_id"] = 1

            with self.assertRaises(ValueError):
                with store.locked_data(write=True) as data:
                    data["active_id"] = 999

    def test_add_details_prints_created_task_details(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = run_tree(tmp_dir, "add", "Detailed task", "--body", "Detailed body", "--details")

            self.assertIn("id: 1", out)
            self.assertIn("summary: Detailed task", out)
            self.assertIn("status: not_started", out)
            self.assertIn("Parent: None", out)
            self.assertIn("body: Detailed body", out)
            self.assertIn("created_at:", out)
            self.assertIn("shared_dir:", out)
            self.assertNotIn("[ ] #1 Detailed task", out)

    def test_add_without_details_prints_compact_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = run_tree(tmp_dir, "add", "Tree output")

            self.assertIn("task_tree_snapshot:", out)
            self.assertIn("next_actionable: [ ] #1 Tree output", out)
            self.assertNotIn("summary: Tree output", out)

    def test_add_full_tree_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = run_tree(tmp_dir, "add", "Tree output", "--full-tree")

            self.assertIn("[ ] #1 Tree output", out)
            self.assertNotIn("task_tree_snapshot:", out)

    def test_add_details_with_files_prints_files_dir_and_creates_directory(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            out = run_tree(tmp_dir, "add", "Task files", "--with-files", "--details")

            files_dir = Path(tmp_dir) / "files" / "1"
            self.assertTrue(files_dir.is_dir())
            self.assertIn(f"files_dir: {files_dir}", out)
            self.assertIn("files_created_at:", out)

    def test_no_args_prints_compact_active_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done before", "--parent", "1", "--status", "completed")
            run_tree(tmp_dir, "add", "Current", "--parent", "1", "--status", "not_started", "--set-active")
            run_tree(tmp_dir, "add", "Next after", "--parent", "1", "--status", "not_started")

            out = run_tree(tmp_dir)

            self.assertIn("task_tree_snapshot:", out)
            self.assertIn("parent: #1 Root", out)
            self.assertIn("previous_sibling: #2 Done before", out)
            self.assertIn("active:", out)
            self.assertIn("summary: Current", out)
            self.assertIn("next_sibling: #4 Next after", out)
            self.assertNotIn("next_after_subtree:", out)
            self.assertFalse(any(line.startswith("[~] #1 Root") for line in out.splitlines()))

    def test_snapshot_shows_next_task_after_parent_subtree_title_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "First branch", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Current", "--parent", "1", "--set-active")
            run_tree(tmp_dir, "add", "Later branch", "--status", "not_started")

            out = run_tree(tmp_dir)

            self.assertIn("parent: #1 First branch", out)
            self.assertIn("next_after_subtree: #3 Later branch", out)
            self.assertNotIn("[ ] #3 Later branch", out)

    def test_snapshot_climbs_ancestors_to_find_next_task_after_subtree(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "First root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Nested branch", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Current", "--parent", "2", "--set-active")
            run_tree(tmp_dir, "add", "Second root", "--status", "not_started")

            out = run_tree(tmp_dir)

            self.assertIn("parent: #2 Nested branch", out)
            self.assertIn("next_after_subtree: #4 Second root", out)

    def test_snapshot_without_active_prints_next_actionable_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "not_started")

            out = run_tree(tmp_dir, "snapshot")

            self.assertIn("active: (no active task)", out)
            self.assertIn("next_actionable: [ ] #1 Root", out)
            self.assertNotIn("previous_sibling:", out)

    def test_reorder_before_first_pending_keeps_completed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done", "--parent", "1", "--status", "completed")
            run_tree(tmp_dir, "add", "Review gate", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Later", "--parent", "1", "--status", "not_started")
            run_tree(tmp_dir, "add", "Inserted", "--parent", "1", "--status", "in_progress")

            out = run_tree(tmp_dir, "reorder", "5", "--before-first-pending", "--full-tree")

            self.assertLess(out.index("#2 Done"), out.index("#5 Inserted"))
            self.assertLess(out.index("#5 Inserted"), out.index("#3 Review gate"))
            self.assertLess(out.index("#3 Review gate"), out.index("#4 Later"))

    def test_reorder_before_first_pending_appends_when_no_pending_siblings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done A", "--parent", "1", "--status", "completed")
            run_tree(tmp_dir, "add", "Inserted", "--parent", "1", "--status", "completed")
            run_tree(tmp_dir, "add", "Done B", "--parent", "1", "--status", "completed")

            out = run_tree(tmp_dir, "reorder", "3", "--before-first-pending", "--full-tree")

            self.assertLess(out.index("#2 Done A"), out.index("#4 Done B"))
            self.assertLess(out.index("#4 Done B"), out.index("#3 Inserted"))

    def test_reorder_after_exact_sibling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "A", "--parent", "1")
            run_tree(tmp_dir, "add", "B", "--parent", "1")
            run_tree(tmp_dir, "add", "C", "--parent", "1")

            out = run_tree(tmp_dir, "reorder", "4", "--after", "2", "--full-tree")

            self.assertLess(out.index("#2 A"), out.index("#4 C"))
            self.assertLess(out.index("#4 C"), out.index("#3 B"))

    def test_reorder_before_exact_sibling(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "A", "--parent", "1")
            run_tree(tmp_dir, "add", "B", "--parent", "1")
            run_tree(tmp_dir, "add", "C", "--parent", "1")

            out = run_tree(tmp_dir, "reorder", "4", "--before", "3", "--full-tree")

            self.assertLess(out.index("#2 A"), out.index("#4 C"))
            self.assertLess(out.index("#4 C"), out.index("#3 B"))

    def test_reorder_rejects_non_sibling_exact_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "A", "--parent", "1")
            run_tree(tmp_dir, "add", "Nested", "--parent", "2")
            run_tree(tmp_dir, "add", "B", "--parent", "1")

            env = os.environ.copy()
            env["TASK_TREE_FILE"] = str(Path(tmp_dir) / "tree.json")
            result = subprocess.run(
                [sys.executable, str(TASK_TREE), "reorder", "4", "--after", "3"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("is not a sibling", result.stderr)


    def test_next_after_completed_active_child_returns_next_pending_tree_node(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Control", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Later top-level", "--parent", "1", "--status", "not_started")
            run_tree(tmp_dir, "add", "Done child", "--parent", "2", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Next child", "--parent", "2", "--status", "not_started")
            run_tree(tmp_dir, "set-active", "4")
            run_tree(tmp_dir, "update", "4", "--status", "completed")

            out = run_tree(tmp_dir, "next")

            self.assertIn("id: 5", out)
            self.assertIn("summary: Next child", out)

    def test_next_on_active_parent_searches_pending_children_first(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done child", "--parent", "1", "--status", "completed")
            run_tree(tmp_dir, "add", "Pending child", "--parent", "1", "--status", "not_started")
            run_tree(tmp_dir, "add", "Other top-level", "--status", "not_started")
            run_tree(tmp_dir, "set-active", "1")

            out = run_tree(tmp_dir, "next")

            self.assertIn("id: 3", out)
            self.assertIn("summary: Pending child", out)

    def test_next_fallback_uses_tree_order_not_numeric_id_order(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root A", "--status", "completed")
            run_tree(tmp_dir, "add", "Root B", "--status", "not_started")
            run_tree(tmp_dir, "add", "Child of A", "--parent", "1", "--status", "not_started")

            out = run_tree(tmp_dir, "next")

            self.assertIn("id: 3", out)
            self.assertIn("summary: Child of A", out)

    def test_next_after_completed_last_child_returns_parent_for_closeout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Control", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done child", "--parent", "2", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Later top-level", "--parent", "1", "--status", "not_started")
            run_tree(tmp_dir, "set-active", "3")
            run_tree(tmp_dir, "update", "3", "--status", "completed")

            out = run_tree(tmp_dir, "next")

            self.assertIn("id: 2", out)
            self.assertIn("summary: Control", out)

    def test_closeout_review_flag_suppresses_repeated_parent_closeout(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Control", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done child", "--parent", "2", "--status", "completed")
            run_tree(tmp_dir, "add", "Later sibling", "--parent", "1", "--status", "not_started")
            run_tree(tmp_dir, "update", "2", "--closeout-reviewed", "true")

            active_parent = run_tree(tmp_dir, "show", "2", "--details")
            out = run_tree(tmp_dir, "next", "3")

            self.assertIn("closeout_reviewed: true", active_parent)
            self.assertNotIn("closeout_review: due", active_parent)
            self.assertIn("id: 2", out)
            self.assertIn("summary: Control", out)
            self.assertNotIn("closeout_review: due", out)

    def test_child_status_change_invalidates_parent_closeout_review_flag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Control", "--parent", "1", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Done child", "--parent", "2", "--status", "completed")
            run_tree(tmp_dir, "update", "2", "--closeout-reviewed", "true")
            run_tree(tmp_dir, "update", "3", "--status", "not_started")

            parent = run_tree(tmp_dir, "show", "2", "--details")

            self.assertIn("closeout_reviewed: false", parent)

    def test_completing_active_task_auto_advances_to_next_pending_tree_node(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "First", "--parent", "1", "--status", "in_progress", "--set-active")
            run_tree(tmp_dir, "add", "Second", "--parent", "1", "--status", "not_started")

            out = run_tree(tmp_dir, "update", "2", "--status", "completed")
            active = run_tree(tmp_dir, "active")

            self.assertIn("previous_sibling: #2 First", out)
            self.assertIn("id: 3", active)
            self.assertIn("summary: Second", active)

    def test_completing_final_active_task_clears_active_pointer(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Only", "--status", "in_progress", "--set-active")

            run_tree(tmp_dir, "update", "1", "--status", "completed")
            active = run_tree(tmp_dir, "active")

            self.assertIn("(no active task)", active)

    def test_set_active_rejects_completed_task(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Done", "--status", "completed")

            env = os.environ.copy()
            env["TASK_TREE_FILE"] = str(Path(tmp_dir) / "tree.json")
            result = subprocess.run(
                [sys.executable, str(TASK_TREE), "set-active", "1"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("Cannot set completed task active: 1", result.stderr)

    def test_add_rejects_completed_task_set_active(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = os.environ.copy()
            env["TASK_TREE_FILE"] = str(Path(tmp_dir) / "tree.json")
            result = subprocess.run(
                [
                    sys.executable,
                    str(TASK_TREE),
                    "add",
                    "Done",
                    "--status",
                    "completed",
                    "--set-active",
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("Cannot set completed task active: 1", result.stderr)

    def test_reset_prunes_task_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--with-files")
            files_dir = Path(tmp_dir) / "files" / "1"
            self.assertTrue(files_dir.is_dir())

            run_tree(tmp_dir, "reset")

            self.assertFalse((Path(tmp_dir) / "files").exists())
            self.assertIn("(no next task)", run_tree(tmp_dir, "next"))

    def test_delete_prunes_task_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--with-files")
            run_tree(tmp_dir, "add", "Child", "--parent", "1", "--with-files")
            root_files = Path(tmp_dir) / "files" / "1"
            child_files = Path(tmp_dir) / "files" / "2"
            self.assertTrue(root_files.is_dir())
            self.assertTrue(child_files.is_dir())

            run_tree(tmp_dir, "delete", "1", "--force")

            self.assertFalse(root_files.exists())
            self.assertFalse(child_files.exists())
            self.assertFalse((Path(tmp_dir) / "files").exists())
            self.assertIn("(no next task)", run_tree(tmp_dir, "next"))


if __name__ == "__main__":
    unittest.main()
