import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"
RUNTIME_MODULES = ("task_tree.py", "task_tree_schema.py", "json_format.py")
LEGACY_FIXTURE = TEST_DIR / "fixtures" / "v1_migration_example" / "legacy-tree.json"


def deploy_runtime(tmp_path: Path) -> tuple[Path, Path]:
    project = tmp_path / "project"
    bundle = project / "runtime"
    bundle.mkdir(parents=True)
    for name in RUNTIME_MODULES:
        shutil.copy2(SCRIPTS_DIR / name, bundle / name)
    return project, bundle / "task_tree.py"


def run_runtime(
    project: Path,
    script: Path,
    *args: str,
    env_updates=None,
) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # The deployment test must prove the three-file bundle is sufficient rather
    # than inheriting repository modules through a developer shell setting.
    env.pop("PYTHONPATH", None)
    env.pop("TASK_TREE_FILE", None)
    env.pop("TASK_TREE_AGENT", None)
    env.update(env_updates or {})
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=project,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def task(node_id=1, *, status="not_started"):
    return {
        "id": node_id,
        "children": [],
        "summary": "Task",
        "body": "",
        "status": status,
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def tree(*, active_id=1):
    return {
        "schema_version": 2,
        "next_id": 2,
        "active_id": active_id,
        "root_ids": [1],
        "nodes": [task()],
    }


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def test_three_module_bundle_supports_help_create_read_and_mutate(tmp_path):
    project, script = deploy_runtime(tmp_path)
    assert sorted(path.name for path in script.parent.iterdir()) == sorted(RUNTIME_MODULES)

    help_result = run_runtime(project, script, "--help")
    assert help_result.returncode == 0, help_result.stderr
    assert "./task_tree/tree.json" in help_result.stdout
    command_lines = help_result.stdout.splitlines()
    show_line = next(line for line in command_lines if "show [id]" in line)
    add_line = next(line for line in command_lines if "add <summary>" in line)
    update_line = next(line for line in command_lines if "update <id>" in line)
    assert "show                [id]" not in help_result.stdout
    assert show_line.index("Show the whole") == add_line.index("Add a task")
    assert show_line.index("Show the whole") == update_line.index("Update an existing")
    assert "Subcommand-specific options:" in help_result.stdout
    assert "--json                      Emit JSON rather than text." in help_result.stdout
    assert "--before ID                 Move the task before sibling ID." in help_result.stdout
    assert "--return-to ID              After this task's subtree finishes" in help_result.stdout
    assert "--event EVENT (required)    Name the event recorded in the task event log." in help_result.stdout

    delete_help = run_runtime(project, script, "delete", "--help")
    assert delete_help.returncode == 0, delete_help.stderr
    assert "--prune-files" not in delete_help.stdout
    assert (
        "If no command is specified, show the compact active-task snapshot."
        in " ".join(help_result.stdout.split())
    )

    empty_snapshot = run_runtime(project, script, "snapshot", "--json")
    assert empty_snapshot.returncode == 0, empty_snapshot.stderr
    assert json.loads(empty_snapshot.stdout) == {
        "active": None,
        "parent": None,
        "previous_sibling": None,
        "next_sibling": None,
        "next_after_subtree": None,
        "next_actionable": None,
        "shared_dir": "./task_tree/shared",
    }

    add_result = run_runtime(project, script, "add", "First task", "--set-active")
    assert add_result.returncode == 0, add_result.stderr
    canonical = project / "task_tree" / "tree.json"
    assert canonical.exists()
    assert not (project / "task_tree" / "tree-v2.json").exists()

    active_result = run_runtime(project, script, "active")
    assert active_result.returncode == 0, active_result.stderr
    assert "summary: First task" in active_result.stdout
    assert "active is deprecated; use snapshot or snapshot --json" in active_result.stderr

    snapshot_json = run_runtime(project, script, "snapshot", "--json")
    assert snapshot_json.returncode == 0, snapshot_json.stderr
    snapshot_payload = json.loads(snapshot_json.stdout)
    assert snapshot_payload["active"]["summary"] == "First task"
    assert snapshot_payload["parent"] is None
    assert snapshot_payload["next_actionable"] is None
    assert snapshot_payload["shared_dir"].endswith("task_tree/shared")

    update_result = run_runtime(project, script, "update", "1", "--summary", "Renamed")
    assert update_result.returncode == 0, update_result.stderr
    assert json.loads(canonical.read_text(encoding="utf-8"))["nodes"][0]["summary"] == "Renamed"


def test_default_runtime_ignores_version_suffixed_sentinel(tmp_path):
    project, script = deploy_runtime(tmp_path)
    sentinel = project / "task_tree" / "tree-v2.json"
    sentinel_bytes = b'"not the canonical store"\n'
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(sentinel_bytes)

    result = run_runtime(project, script, "add", "Canonical task")

    assert result.returncode == 0, result.stderr
    assert (project / "task_tree" / "tree.json").exists()
    assert sentinel.read_bytes() == sentinel_bytes


def test_legacy_environment_store_selection_warns_and_does_not_add_version_suffix(tmp_path):
    project, script = deploy_runtime(tmp_path)

    agent_result = run_runtime(
        project,
        script,
        "add",
        "Agent task",
        env_updates={"TASK_TREE_AGENT": "Review Agent"},
    )
    assert agent_result.returncode == 0, agent_result.stderr
    assert (project / "task_tree" / "review-agent.json").exists()
    assert not (project / "task_tree" / "review-agent-v2.json").exists()
    assert "TASK_TREE_AGENT is deprecated" in agent_result.stderr
    assert "--tree-file ./task_tree/review-agent.json" in agent_result.stderr

    explicit = project / "custom" / "tasks.json"
    explicit_result = run_runtime(
        project,
        script,
        "add",
        "Explicit task",
        env_updates={"TASK_TREE_FILE": str(explicit)},
    )
    assert explicit_result.returncode == 0, explicit_result.stderr
    assert explicit.exists()
    assert "TASK_TREE_FILE is deprecated" in explicit_result.stderr
    assert f"--tree-file {explicit}" in explicit_result.stderr


def test_cli_tree_file_selects_store_and_overrides_environment(tmp_path):
    project, script = deploy_runtime(tmp_path)
    environment_store = project / "environment" / "tree.json"
    cli_store = project / "selected" / "custom.json"

    result = run_runtime(
        project,
        script,
        "--tree-file",
        str(cli_store),
        "add",
        "CLI-selected task",
        env_updates={
            "TASK_TREE_FILE": str(environment_store),
            "TASK_TREE_AGENT": "Ignored Agent",
        },
    )

    assert result.returncode == 0, result.stderr
    assert cli_store.exists()
    assert not environment_store.exists()
    assert not (project / "task_tree" / "ignored-agent.json").exists()
    assert result.stderr == ""
    persisted = json.loads(cli_store.read_text(encoding="utf-8"))
    assert persisted["nodes"][0]["summary"] == "CLI-selected task"


def test_cli_tree_file_parent_owns_tree_artifacts(tmp_path):
    project, script = deploy_runtime(tmp_path)
    cli_store = project / "selected" / "custom.json"

    add_result = run_runtime(
        project,
        script,
        "--tree-file",
        str(cli_store),
        "add",
        "Task with files",
        "--with-files",
    )
    shared_result = run_runtime(
        project,
        script,
        "--tree-file",
        str(cli_store),
        "shared-dir",
    )

    assert add_result.returncode == 0, add_result.stderr
    assert shared_result.returncode == 0, shared_result.stderr
    assert (cli_store.parent / "files" / "1").is_dir()
    assert (cli_store.parent / "shared").is_dir()
    assert Path(f"{cli_store}.lock").exists()


def test_legacy_read_requires_manual_migration_without_rewriting(tmp_path):
    project, script = deploy_runtime(tmp_path)
    legacy = project / "legacy.json"
    legacy.write_bytes(LEGACY_FIXTURE.read_bytes())
    before = legacy.read_bytes()

    result = run_runtime(
        project,
        script,
        "show",
        env_updates={"TASK_TREE_FILE": str(legacy)},
    )

    assert result.returncode == 2
    assert "old task-tree format detected" in result.stderr
    assert "manual migration utility" in result.stderr
    assert legacy.read_bytes() == before


def test_read_initializes_and_persists_missing_version_on_populated_current_tree(
    tmp_path,
):
    project, script = deploy_runtime(tmp_path)
    path = project / "tree.json"
    data = tree()
    data.pop("schema_version")
    write_json(path, data)

    result = run_runtime(
        project,
        script,
        "show",
        env_updates={"TASK_TREE_FILE": str(path)},
    )

    assert result.returncode == 0, result.stderr
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["schema_version"] == 2
    assert persisted["root_ids"] == [1]
    assert persisted["nodes"] == data["nodes"]


def test_missing_version_is_not_persisted_when_current_graph_is_invalid(tmp_path):
    project, script = deploy_runtime(tmp_path)
    path = project / "tree.json"
    data = tree()
    data.pop("schema_version")
    data["root_ids"] = []
    write_json(path, data)
    before = path.read_bytes()

    result = run_runtime(
        project,
        script,
        "show",
        env_updates={"TASK_TREE_FILE": str(path)},
    )

    assert result.returncode == 2
    assert "owning position" in result.stderr
    assert path.read_bytes() == before


def test_empty_tree_without_version_is_not_inferred_or_rewritten(tmp_path):
    project, script = deploy_runtime(tmp_path)
    path = project / "tree.json"
    data = {
        "next_id": 1,
        "active_id": None,
        "root_ids": [],
        "nodes": [],
    }
    write_json(path, data)
    before = path.read_bytes()

    result = run_runtime(
        project,
        script,
        "show",
        env_updates={"TASK_TREE_FILE": str(path)},
    )

    assert result.returncode == 2
    assert "missing required schema_version" in result.stderr
    assert path.read_bytes() == before


def test_clear_active_repairs_only_the_invalid_focus_pointer(tmp_path):
    project, script = deploy_runtime(tmp_path)
    path = project / "tree.json"
    write_json(path, tree(active_id=99))
    env = {"TASK_TREE_FILE": str(path)}

    rejected = run_runtime(project, script, "snapshot", env_updates=env)
    assert rejected.returncode == 2
    assert "active_id references missing node 99" in rejected.stderr

    repaired = run_runtime(project, script, "clear-active", env_updates=env)
    assert repaired.returncode == 0, repaired.stderr
    assert json.loads(path.read_text(encoding="utf-8"))["active_id"] is None


def test_clear_active_does_not_rewrite_structurally_invalid_tree(tmp_path):
    project, script = deploy_runtime(tmp_path)
    path = project / "tree.json"
    data = tree(active_id=99)
    data["root_ids"] = []
    write_json(path, data)
    before = path.read_bytes()

    result = run_runtime(
        project,
        script,
        "clear-active",
        env_updates={"TASK_TREE_FILE": str(path)},
    )

    assert result.returncode == 2
    assert "owning position" in result.stderr
    assert path.read_bytes() == before


def test_malformed_json_has_readable_error_and_is_not_rewritten(tmp_path):
    project, script = deploy_runtime(tmp_path)
    path = project / "broken.json"
    path.write_text("{not-json\n", encoding="utf-8")
    before = path.read_bytes()

    result = run_runtime(
        project,
        script,
        "show",
        env_updates={"TASK_TREE_FILE": str(path)},
    )

    assert result.returncode == 2
    assert "Expecting property name" in result.stderr
    assert path.read_bytes() == before
