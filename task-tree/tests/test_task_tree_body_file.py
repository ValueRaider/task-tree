from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_tree.py"


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "TASK_TREE_FILE": str(tmp_path / "tree.json")}
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_update_body_file_sets_exact_multiline_body(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Body-file task").returncode == 0
    body_path = tmp_path / "body.txt"
    body = "first line\nsecond line\n-- literal leading dashes are data\n"
    body_path.write_text(body, encoding="utf-8")

    result = _run(tmp_path, "update", "1", "--body-file", str(body_path), "--details")

    assert result.returncode == 0, result.stderr
    assert "body: first line" in result.stdout
    assert "second line" in result.stdout
    assert "-- literal leading dashes are data" in result.stdout


def test_update_body_still_sets_inline_body(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Inline body task").returncode == 0

    result = _run(tmp_path, "update", "1", "--body", "inline body", "--details")

    assert result.returncode == 0, result.stderr
    assert "body: inline body" in result.stdout


def test_update_rejects_body_and_body_file_together(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Rejected body task").returncode == 0
    body_path = tmp_path / "body.txt"
    body_path.write_text("from file", encoding="utf-8")

    result = _run(tmp_path, "update", "1", "--body", "inline", "--body-file", str(body_path))

    assert result.returncode != 0
    assert "not allowed with argument" in result.stderr
