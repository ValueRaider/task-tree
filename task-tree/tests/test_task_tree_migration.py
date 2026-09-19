import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
MIGRATOR = SKILL_DIR / "experiments" / "v2" / "migrate_v1_to_v2.py"
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE_DIR = TEST_DIR / "fixtures" / "v1_migration_example"
FIXTURE = FIXTURE_DIR / "legacy-tree.json"

sys.path.insert(0, str(SCRIPTS_DIR))
from task_tree_schema import validate_tree

spec = importlib.util.spec_from_file_location("task_tree_v2_migrator", MIGRATOR)
migrator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrator)


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def node_by_id(data, node_id):
    return next(node for node in data["nodes"] if node["id"] == node_id)


def test_migration_places_membership_and_order_at_parent():
    source = load_fixture()

    migrated = migrator.migrate_v1_data(source)

    assert migrated["schema_version"] == 2
    assert migrated["root_ids"] == [2, 1]
    assert node_by_id(migrated, 1)["children"] == [3, 5, 4, 7, 9]
    assert node_by_id(migrated, 4)["children"] == [6]
    assert node_by_id(migrated, 7)["children"] == [8]
    assert node_by_id(migrated, 2)["children"] == []
    assert all("parent_id" not in node for node in migrated["nodes"])
    assert all("sibling_order" not in node for node in migrated["nodes"])


def test_migration_preserves_payload_and_does_not_mutate_source():
    source = load_fixture()
    original = copy.deepcopy(source)

    migrated = migrator.migrate_v1_data(source)

    assert source == original
    old_active = node_by_id(source, 4)
    new_active = node_by_id(migrated, 4)
    for field in (
        "id",
        "summary",
        "body",
        "status",
        "closeout_reviewed",
        "files_dir",
        "events",
    ):
        assert new_active[field] == old_active[field]
    assert migrated["active_id"] == source["active_id"]
    assert migrated["next_id"] == source["next_id"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda data: data["nodes"].append(copy.deepcopy(data["nodes"][0])), "duplicate node id"),
        (lambda data: data["nodes"][2].update(parent_id=999), "missing parent"),
        (lambda data: data["nodes"][0].update(parent_id=8), "unreachable"),
        (lambda data: data.update(active_id=3), "non-actionable status"),
        (lambda data: data.update(next_id=9), "next_id must be greater"),
        (lambda data: data.update(schema_version=9), "expected legacy schema version"),
    ],
)
def test_migration_rejects_invalid_legacy_graphs(mutation, message):
    source = load_fixture()
    mutation(source)

    with pytest.raises(migrator.MigrationError, match=message):
        migrator.migrate_v1_data(source)


def test_output_mode_writes_new_v2_file(tmp_path):
    source = tmp_path / "legacy.json"
    output = tmp_path / "v2.json"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MIGRATOR), str(source), "--output", str(output)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    migrated = json.loads(output.read_text(encoding="utf-8"))
    validate_tree(migrated)
    assert json.loads(source.read_text(encoding="utf-8")) == load_fixture()


def test_in_place_mode_backs_up_legacy_before_replacement(tmp_path):
    source = tmp_path / "tree.json"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MIGRATOR), str(source), "--in-place"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    backup = tmp_path / "tree.json.v1.bak"
    assert json.loads(backup.read_text(encoding="utf-8")) == load_fixture()
    validate_tree(json.loads(source.read_text(encoding="utf-8")))


def test_in_place_mode_refuses_to_overwrite_existing_backup(tmp_path):
    source = tmp_path / "tree.json"
    backup = tmp_path / "tree.json.v1.bak"
    source.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    backup.write_text("do not overwrite", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MIGRATOR), str(source), "--in-place"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "backup already exists" in result.stderr
    assert json.loads(source.read_text(encoding="utf-8")) == load_fixture()
    assert backup.read_text(encoding="utf-8") == "do not overwrite"
