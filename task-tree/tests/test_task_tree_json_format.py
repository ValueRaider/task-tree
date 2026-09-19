import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
V2_DIR = SKILL_DIR / "experiments" / "v2"
MIGRATOR = V2_DIR / "migrate_v1_to_v2.py"
TASK_TREE = SKILL_DIR / "scripts" / "task_tree.py"
LEGACY_FIXTURE = TEST_DIR / "fixtures" / "v1_migration_example" / "legacy-tree.json"
CURRENT_FIXTURE = TEST_DIR / "fixtures" / "current_task_tree_example" / "tree.json"

sys.path.insert(0, str(SKILL_DIR / "scripts"))
from json_format import RELATIONSHIP_ARRAY_LINE_WIDTH, dumps_v2_json


def test_relationship_arrays_share_lines_with_their_property_names():
    data = {
        "schema_version": 2,
        "next_id": 61,
        "active_id": None,
        "root_ids": [1, 2],
        "nodes": [
            {
                "id": 1,
                "children": [3, 4, 28, 34, 5, 6, 7, 9, 60, 39],
            }
        ],
    }

    rendered = dumps_v2_json(data)

    assert '  "root_ids": [1, 2],' in rendered
    assert '      "children": [3, 4, 28, 34, 5, 6, 7, 9, 60, 39],' in rendered
    assert json.loads(rendered) == data


def test_long_relationship_arrays_wrap_within_documented_width():
    data = {"root_ids": list(range(1, 121)), "nodes": []}

    rendered = dumps_v2_json(data)

    assert json.loads(rendered) == data
    assert max(len(line) for line in rendered.splitlines()) <= RELATIONSHIP_ARRAY_LINE_WIDTH
    relationship_lines = [
        line
        for line in rendered.splitlines()
        if '"root_ids": [' in line or line.startswith(" " * len('  "root_ids": ['))
    ]
    assert len(relationship_lines) > 1


def test_migrator_writes_compact_parent_owned_arrays(tmp_path: Path):
    output = tmp_path / "tree-v2.json"

    result = subprocess.run(
        [sys.executable, str(MIGRATOR), str(LEGACY_FIXTURE), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    rendered = output.read_text(encoding="utf-8")
    assert '  "root_ids": [2, 1],' in rendered
    assert '      "children": [3, 5, 4, 7, 9],' in rendered


def test_runtime_mutation_preserves_compact_array_format(tmp_path: Path):
    tree = tmp_path / "tree.json"
    shutil.copy2(CURRENT_FIXTURE, tree)
    env = dict(os.environ, TASK_TREE_FILE=str(tree))

    mutation = subprocess.run(
        [sys.executable, str(TASK_TREE), "reorder", "5", "--after", "4"],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert mutation.returncode == 0, mutation.stderr
    rendered = tree.read_text(encoding="utf-8")
    assert '      "children": [3, 4, 5, 7, 9],' in rendered
    assert json.loads(rendered)["schema_version"] == 2
