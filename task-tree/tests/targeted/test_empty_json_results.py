"""Public CLI regressions for structured empty output."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = TEST_DIR / "scripts"
TASK_TREE = SCRIPTS_DIR / "task_tree.py"


def _run_tree(tree_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TASK_TREE), "--tree-dir", str(tree_dir), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_empty_json_keeps_each_command_envelope_and_text_prose(tmp_path):
    tree_dir = tmp_path / "store"
    assert _run_tree(tree_dir, "add", "Root").returncode == 0

    cases = [
        (("list", "--status", "completed", "--json"), {"active_id": None, "nodes": []}),
        (("children", "1", "--json"), {"active_id": None, "parent_id": 1, "nodes": []}),
        (
            ("query", "--contains", "no-such-summary", "--json"),
            {
                "active_id": None,
                "query": {
                    "status": None,
                    "contains": "no-such-summary",
                    "event": "last_mutated_at",
                    "since_days": None,
                },
                "nodes": [],
            },
        ),
    ]
    for args, expected in cases:
        result = _run_tree(tree_dir, *args)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == expected

    assert _run_tree(tree_dir, "list", "--status", "completed").stdout.strip() == "(no matching tasks)"
    assert _run_tree(tree_dir, "children", "1").stdout.strip() == "(no child tasks)"
    assert _run_tree(tree_dir, "query", "--contains", "no-such-summary").stdout.strip() == "(no matching tasks)"
