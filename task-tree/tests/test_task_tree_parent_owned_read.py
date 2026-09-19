import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"
CURRENT_FIXTURE = TEST_DIR / "fixtures" / "current_task_tree_example" / "tree.json"
BASELINE_DIR = TEST_DIR / "fixtures" / "v1_migration_example"
LEGACY_FIXTURE = BASELINE_DIR / "legacy-tree.json"


def copy_fixture(tmp_path: Path) -> Path:
    output = tmp_path / "tree.json"
    shutil.copy2(CURRENT_FIXTURE, output)
    return output


def run_tree(tree: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["TASK_TREE_FILE"] = str(tree)
    return subprocess.run(
        [sys.executable, str(TASK_TREE), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_full_tree_render_matches_pre_migration_baseline(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "show")

    assert result.returncode == 0, result.stderr
    assert result.stdout == (BASELINE_DIR / "expected-full-tree.txt").read_text(
        encoding="utf-8"
    )


def test_path_matches_pre_migration_baseline(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "path", "6")

    assert result.returncode == 0, result.stderr
    assert result.stdout == (BASELINE_DIR / "expected-path-to-6.txt").read_text(
        encoding="utf-8"
    )


def test_next_preserves_active_descendant_priority(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "next")

    assert result.returncode == 0, result.stderr
    assert "id: 6\nsummary: Nested pending child\nstatus: not_started" in result.stdout
    assert "Parent: [~] #4 Active middle child << ACTIVE" in result.stdout


def test_children_json_derives_compatibility_relationship_fields(tmp_path: Path):
    tree = copy_fixture(tmp_path)

    result = run_tree(tree, "children", "1", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert [node["id"] for node in payload["nodes"]] == [3, 5, 4, 7, 9]
    assert [node["sibling_order"] for node in payload["nodes"]] == [1, 2, 3, 4, 5]
    assert all(node["parent_id"] == 1 for node in payload["nodes"])


def test_runtime_rejects_unmigrated_legacy_tree(tmp_path: Path):
    legacy_copy = tmp_path / "legacy-tree.json"
    legacy_copy.write_text(
        LEGACY_FIXTURE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = run_tree(legacy_copy, "show")

    assert result.returncode == 2
    assert "old task-tree format detected" in result.stderr
    assert "manual migration utility" in result.stderr
