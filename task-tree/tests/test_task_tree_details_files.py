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


def test_details_lists_sorted_relative_task_files(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Artifact task", "--with-files").returncode == 0
    files_dir = tmp_path / "files" / "1"
    (files_dir / "zeta.txt").write_text("z", encoding="utf-8")
    (files_dir / "notes").mkdir()
    (files_dir / "notes" / "alpha.md").write_text("a", encoding="utf-8")

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    assert "files:\n  - notes/alpha.md\n  - zeta.txt" in result.stdout


def test_details_reports_empty_task_directory(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Empty artifact task", "--with-files").returncode == 0

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    assert "files:\n  (none)" in result.stdout


def test_details_truncates_file_list_after_ten_paths(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Large artifact task", "--with-files").returncode == 0
    files_dir = tmp_path / "files" / "1"
    for index in range(12):
        (files_dir / f"artifact_{index:02}.txt").write_text(str(index), encoding="utf-8")

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    for index in range(10):
        assert f"  - artifact_{index:02}.txt" in result.stdout
    assert "artifact_10.txt" not in result.stdout
    assert "artifact_11.txt" not in result.stdout
    assert "  ... 2 more files" in result.stdout


def test_details_lists_only_direct_children_with_state_and_active_marker(
    tmp_path: Path,
) -> None:
    assert _run(tmp_path, "add", "Root").returncode == 0
    assert _run(tmp_path, "add", "First", "--parent", "1").returncode == 0
    assert _run(
        tmp_path, "add", "Second", "--parent", "1", "--status", "in_progress"
    ).returncode == 0
    assert _run(
        tmp_path, "add", "Third", "--parent", "1", "--status", "completed"
    ).returncode == 0
    assert _run(tmp_path, "add", "Grandchild", "--parent", "2").returncode == 0
    assert _run(tmp_path, "set-active", "3").returncode == 0

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    assert "children:" in result.stdout
    assert "  [ ] #2 First" in result.stdout
    assert "  [~] #3 Second << ACTIVE" in result.stdout
    assert "  [x] #4 Third" in result.stdout
    assert "Grandchild" not in result.stdout


def test_details_truncates_direct_children_after_three(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Root").returncode == 0
    for index in range(5):
        assert _run(tmp_path, "add", f"Child {index}", "--parent", "1").returncode == 0

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    for index in range(3):
        assert f"Child {index}" in result.stdout
    assert "Child 3" not in result.stdout
    assert "Child 4" not in result.stdout
    assert "  ... 2 more children" in result.stdout


def test_details_reports_when_task_has_no_children(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Leaf").returncode == 0

    result = _run(tmp_path, "show", "1", "--details")

    assert result.returncode == 0, result.stderr
    assert "children:\n  (none)" in result.stdout


def test_details_prints_parent_id_and_title_on_one_line(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Named parent").returncode == 0
    assert _run(tmp_path, "add", "Child", "--parent", "1").returncode == 0
    assert _run(tmp_path, "set-active", "1").returncode == 0

    child = _run(tmp_path, "show", "2", "--details")
    root = _run(tmp_path, "show", "1", "--details")

    assert child.returncode == 0, child.stderr
    assert "Parent: [ ] #1 Named parent << ACTIVE" in child.stdout
    assert "parent_id:" not in child.stdout
    assert "parent_title:" not in child.stdout
    assert root.returncode == 0, root.stderr
    assert "Parent: None" in root.stdout
