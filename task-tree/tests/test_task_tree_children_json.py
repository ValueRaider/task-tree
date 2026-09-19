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


class TaskTreeChildrenJsonTest(unittest.TestCase):
    def test_children_json_keeps_full_payload_when_short(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            run_tree(tmp_dir, "add", "Child", "--parent", "1", "--body", "small body")

            payload = json.loads(run_tree(tmp_dir, "children", "1", "--json"))

            self.assertNotIn("compact", payload)
            self.assertEqual(payload["nodes"][0]["summary"], "Child")
            self.assertEqual(payload["nodes"][0]["body"], "small body")
            self.assertIn("events", payload["nodes"][0])

    def test_children_json_compacts_when_full_payload_is_long(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_tree(tmp_dir, "add", "Root", "--status", "in_progress")
            for index in range(25):
                run_tree(tmp_dir, "add", f"Child {index}", "--parent", "1")

            payload = json.loads(run_tree(tmp_dir, "children", "1", "--json"))

            self.assertTrue(payload["compact"])
            self.assertGreater(payload["full_output_line_count"], 200)
            self.assertEqual(payload["line_limit"], 200)
            self.assertEqual(payload["nodes"][0]["summary"], "Child 0")
            self.assertEqual(payload["nodes"][-1]["summary"], "Child 24")
            self.assertNotIn("body", payload["nodes"][0])
            self.assertNotIn("events", payload["nodes"][0])


if __name__ == "__main__":
    unittest.main()
