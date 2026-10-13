"""Public CLI witness that pruning one store preserves another store's artifacts."""

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "task_tree.py"


def _run(store: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tree-dir", str(store), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_pruning_one_directory_removes_only_its_orphan_artifact(tmp_path):
    store_a = tmp_path / "store-a"
    store_b = tmp_path / "store-b"
    assert _run(store_a, "add", "A live evidence", "--with-files").returncode == 0
    assert _run(store_b, "add", "B live task", "--with-files").returncode == 0

    evidence_a = store_a / "files" / "1" / "evidence.txt"
    evidence_a.write_bytes(b"A referenced evidence\x00\n")
    orphan_b = store_b / "files" / "2" / "orphan.txt"
    orphan_b.parent.mkdir()
    orphan_b.write_bytes(b"B orphan evidence\x00\n")

    a_tree_before = (store_a / "tree.json").read_bytes()
    a_evidence_before = evidence_a.read_bytes()

    prune = _run(store_b, "scan-files", "--prune", "--json")

    assert prune.returncode == 0, prune.stderr
    assert json.loads(prune.stdout)["removed"] == [
        {"path": str(orphan_b.parent), "task_id": 2}
    ]
    assert not orphan_b.parent.exists()
    assert (store_b / "files" / "1").is_dir()
    assert (store_a / "tree.json").read_bytes() == a_tree_before
    assert evidence_a.read_bytes() == a_evidence_before
