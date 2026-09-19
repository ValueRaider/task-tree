import os
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SCRIPT = TEST_DIR.parent / "scripts" / "task_tree.py"


def run_tree(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "TASK_TREE_FILE": str(tmp_path / "tree.json")}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_update_requires_a_mutation_field_but_accepts_each_field(tmp_path):
    created = run_tree(tmp_path, "add", "Original")
    assert created.returncode == 0, created.stderr

    for command in (("update", "1"), ("update", "1", "--details"), ("update", "1", "--full-tree")):
        result = run_tree(tmp_path, *command)
        assert result.returncode == 2
        assert "update requires at least one of" in result.stderr

    body_file = tmp_path / "body.txt"
    body_file.write_text("replacement body", encoding="utf-8")
    for command in (
        ("update", "1", "--summary", "Renamed"),
        ("update", "1", "--body", "inline body"),
        ("update", "1", "--body-file", str(body_file)),
        ("update", "1", "--status", "in_progress"),
        ("update", "1", "--closeout-reviewed", "true"),
        ("update", "1", "--clear-return-to"),
    ):
        result = run_tree(tmp_path, *command)
        assert result.returncode == 0, result.stderr
