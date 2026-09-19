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


def test_rejects_output_modes_that_the_handler_would_otherwise_ignore(tmp_path):
    created = run_tree(tmp_path, "add", "Root")
    assert created.returncode == 0, created.stderr

    no_id_details = run_tree(tmp_path, "show", "--details")
    assert no_id_details.returncode == 2
    assert "show --details requires ID" in no_id_details.stderr

    for command in (
        ("show", "1", "--details", "--json"),
        ("children", "1", "--details", "--json"),
        ("query", "--details", "--json"),
    ):
        result = run_tree(tmp_path, *command)
        assert result.returncode == 2
        assert "not allowed with argument" in result.stderr

    for command in (
        ("show", "1", "--details"),
        ("show", "1", "--json"),
        ("children", "1", "--details"),
        ("children", "1", "--json"),
        ("query", "--details"),
        ("query", "--json"),
    ):
        result = run_tree(tmp_path, *command)
        assert result.returncode == 0, result.stderr
