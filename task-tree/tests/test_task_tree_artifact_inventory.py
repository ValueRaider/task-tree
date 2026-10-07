from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "task_tree.py"


def run_tree(
    tmp_path: Path,
    *args: str,
    tree_file: Path | str | None = None,
) -> subprocess.CompletedProcess[str]:
    selected = tree_file if tree_file is not None else tmp_path / "tree.json"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tree-file", str(selected), *args],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def load_tree(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_scan_files_classifies_only_canonical_non_symlink_directories(tmp_path: Path) -> None:
    assert run_tree(tmp_path, "add", "Live", "--with-files").returncode == 0
    assert run_tree(tmp_path, "add", "Detached").returncode == 0
    files_root = tmp_path / "files"
    (files_root / "1" / "notes").mkdir()
    (files_root / "1" / "notes" / "keep.txt").write_text("live", encoding="utf-8")
    (files_root / "2").mkdir()
    (files_root / "03").mkdir()
    (files_root / "4").write_text("not a directory", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (files_root / "5").symlink_to(outside, target_is_directory=True)

    result = run_tree(tmp_path, "scan-files", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert list(payload) == [
        "files_root",
        "live",
        "orphaned",
        "suspicious",
        "removed",
        "failed",
    ]
    assert payload["live"] == [{"path": str(files_root / "1"), "task_id": 1}]
    assert payload["orphaned"] == [{"path": str(files_root / "2"), "task_id": 2}]
    assert payload["removed"] == []
    assert payload["failed"] == []
    assert {(item["path"], item["reason"]) for item in payload["suspicious"]} == {
        (
            str(files_root / "03"),
            "directory name is not a canonical positive task ID",
        ),
        (str(files_root / "4"), "entry is not a directory"),
        (str(files_root / "5"), "entry is a symlink"),
    }
    assert (files_root / "1" / "notes" / "keep.txt").read_text(encoding="utf-8") == "live"


def test_scan_files_prunes_orphans_without_a_tree_and_is_idempotent(tmp_path: Path) -> None:
    files_root = tmp_path / "files"
    orphan = files_root / "1"
    orphan.mkdir(parents=True)
    (orphan / "recovery.txt").write_text("stale", encoding="utf-8")
    suspicious = files_root / "manual"
    suspicious.mkdir()

    first = run_tree(tmp_path, "scan-files", "--prune", "--json")

    assert first.returncode == 0, first.stderr
    payload = json.loads(first.stdout)
    assert payload["orphaned"] == [{"path": str(orphan), "task_id": 1}]
    assert payload["removed"] == [{"path": str(orphan), "task_id": 1}]
    assert not orphan.exists()
    assert suspicious.is_dir()
    assert not (tmp_path / "tree.json").exists()

    second = run_tree(tmp_path, "scan-files", "--prune", "--json")

    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    assert second_payload["orphaned"] == []
    assert second_payload["removed"] == []
    assert second_payload["suspicious"] == payload["suspicious"]


def test_reset_id_reuse_cannot_adopt_a_residual_directory(tmp_path: Path) -> None:
    tree_path = tmp_path / "tree.json"
    assert run_tree(tmp_path, "add", "Old", "--with-files").returncode == 0
    assert run_tree(tmp_path, "reset").returncode == 0
    residual = tmp_path / "files" / "1"
    residual.mkdir(parents=True)
    evidence = residual / "old-evidence.txt"
    evidence.write_text("preserve", encoding="utf-8")

    result = run_tree(tmp_path, "add", "Reused ID", "--with-files")

    assert result.returncode == 2
    assert "artifact path collision for task 1" in result.stderr
    assert "scan-files --prune" in result.stderr
    assert evidence.read_text(encoding="utf-8") == "preserve"
    data = load_tree(tree_path)
    assert data["next_id"] == 1
    assert data["nodes"] == []


def test_ensure_files_collision_leaves_null_metadata_and_recovery_data(tmp_path: Path) -> None:
    tree_path = tmp_path / "tree.json"
    assert run_tree(tmp_path, "add", "Needs files").returncode == 0
    residual = tmp_path / "files" / "1"
    residual.mkdir(parents=True)
    evidence = residual / "recover.txt"
    evidence.write_text("keep", encoding="utf-8")

    result = run_tree(tmp_path, "ensure-files", "1")

    assert result.returncode == 2
    assert "inspect it or run scan-files --prune" in result.stderr
    assert load_tree(tree_path)["nodes"][0]["files_dir"] is None
    assert evidence.read_text(encoding="utf-8") == "keep"


def test_existing_canonical_relative_and_absolute_spellings_remain_usable(
    tmp_path: Path,
) -> None:
    tree_path = tmp_path / "tree.json"
    assert run_tree(tmp_path, "add", "Canonical").returncode == 0
    first = run_tree(tmp_path, "ensure-files", "1")
    assert first.returncode == 0, first.stderr
    assert first.stdout.strip() == str(tmp_path / "files" / "1")

    data = load_tree(tree_path)
    data["nodes"][0]["files_dir"] = "files/1"
    tree_path.write_text(json.dumps(data), encoding="utf-8")

    relative = run_tree(tmp_path, "ensure-files", "1")

    assert relative.returncode == 0, relative.stderr
    assert relative.stdout.strip() == "files/1"
    assert load_tree(tree_path)["nodes"][0]["files_dir"] == "files/1"


def test_custom_relative_tree_location_owns_its_sibling_files_root(tmp_path: Path) -> None:
    selected = Path("state") / "custom.json"
    assert run_tree(tmp_path, "add", "Custom", tree_file=selected).returncode == 0
    ensured = run_tree(tmp_path, "ensure-files", "1", tree_file=selected)
    assert ensured.returncode == 0, ensured.stderr
    assert ensured.stdout.strip() == "state/files/1"

    scanned = run_tree(tmp_path, "scan-files", "--json", tree_file=selected)

    assert scanned.returncode == 0, scanned.stderr
    payload = json.loads(scanned.stdout)
    assert payload["files_root"] == "state/files"
    assert payload["live"] == [{"path": "state/files/1", "task_id": 1}]


def test_unmanaged_metadata_is_reported_and_rejected_for_creation(tmp_path: Path) -> None:
    tree_path = tmp_path / "tree.json"
    assert run_tree(tmp_path, "add", "Edited").returncode == 0
    data = load_tree(tree_path)
    unmanaged = tmp_path / "elsewhere" / "1"
    data["nodes"][0]["files_dir"] = str(unmanaged)
    tree_path.write_text(json.dumps(data), encoding="utf-8")

    scanned = run_tree(tmp_path, "scan-files", "--json")
    ensured = run_tree(tmp_path, "ensure-files", "1")

    assert scanned.returncode == 0, scanned.stderr
    assert json.loads(scanned.stdout)["suspicious"] == [
        {
            "path": str(unmanaged),
            "task_id": 1,
            "reason": "files_dir is not the task's canonical managed path",
        }
    ]
    assert ensured.returncode == 2
    assert "is unmanaged" in ensured.stderr
    assert not unmanaged.exists()


def test_files_root_symlink_is_reported_and_never_pruned(tmp_path: Path) -> None:
    target = tmp_path / "external-files"
    orphan = target / "1"
    orphan.mkdir(parents=True)
    evidence = orphan / "keep.txt"
    evidence.write_text("keep", encoding="utf-8")
    (tmp_path / "files").symlink_to(target, target_is_directory=True)

    result = run_tree(tmp_path, "scan-files", "--prune", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["orphaned"] == []
    assert payload["removed"] == []
    assert payload["suspicious"] == [
        {"path": str(tmp_path / "files"), "reason": "files root is a symlink"}
    ]
    assert evidence.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("held_lock", "scan_args"),
    [
        (fcntl.LOCK_EX, ("scan-files", "--json")),
        (fcntl.LOCK_SH, ("scan-files", "--prune", "--json")),
    ],
)
def test_scan_files_serializes_with_the_store_lock(
    tmp_path: Path, held_lock: int, scan_args: tuple[str, ...]
) -> None:
    tree_path = tmp_path / "tree.json"
    assert run_tree(tmp_path, "add", "Lock target").returncode == 0
    lock_path = Path(f"{tree_path}.lock")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), held_lock)
        process = subprocess.Popen(
            [
                sys.executable,
                str(SCRIPT),
                "--tree-file",
                str(tree_path),
                *scan_args,
            ],
            cwd=tmp_path,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        assert process.poll() is None
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stderr
    assert json.loads(stdout)["files_root"] == str(tmp_path / "files")
