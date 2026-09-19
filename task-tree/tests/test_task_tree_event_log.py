from __future__ import annotations

import json
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


def _tree_data(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "tree.json").read_text(encoding="utf-8"))


def _event_log_path(tmp_path: Path, node_id: int) -> Path:
    return tmp_path / "files" / str(node_id) / "events.jsonl"


def _event_records(tmp_path: Path, node_id: int) -> list[dict]:
    path = _event_log_path(tmp_path, node_id)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_log_event_creates_event_log_without_polluting_tree_lifecycle_events(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Progress task").returncode == 0

    result = _run(
        tmp_path,
        "log-event",
        "1",
        "--event",
        "repair_completed",
        "--summary",
        "Fixed section binding regression",
        "--phase",
        "validation",
        "--next-action",
        "Re-run focused validation",
        "--command",
        "pytest tests/test_task_tree_reorder.py",
        "--exit-code",
        "0",
        "--blocker",
        "none",
        "--evidence",
        "task_tree/files/1/repair.log",
        "--changed-file",
        ".agents/skills/task-tree/scripts/task_tree.py",
        "--delegate-report",
        "task_tree/files/1002/delegated_implementation_report.md",
    )

    assert result.returncode == 0, result.stderr
    log_path = _event_log_path(tmp_path, 1)
    assert log_path.is_file()

    records = _event_records(tmp_path, 1)
    assert records == [
        {
            "ts": records[0]["ts"],
            "event": "repair_completed",
            "summary": "Fixed section binding regression",
            "phase": "validation",
            "next_action": "Re-run focused validation",
            "command": "pytest tests/test_task_tree_reorder.py",
            "exit_code": 0,
            "blocker": "none",
            "evidence": ["task_tree/files/1/repair.log"],
            "changed_file": [".agents/skills/task-tree/scripts/task_tree.py"],
            "delegate_report": ["task_tree/files/1002/delegated_implementation_report.md"],
        }
    ]
    assert log_path.read_text(encoding="utf-8").count("\n") == 1

    data = _tree_data(tmp_path)
    node = data["nodes"][0]
    assert node["files_dir"] == str(tmp_path / "files" / "1")
    assert "repair_completed" not in node["events"]
    assert "files_created_at" in node["events"]


def test_event_log_tail_and_show_details_only_surface_latest_summary(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Tail task").returncode == 0
    assert _run(tmp_path, "log-event", "1", "--event", "started", "--summary", "Started investigation").returncode == 0
    assert _run(tmp_path, "log-event", "1", "--event", "finished", "--summary", "Finished investigation").returncode == 0

    tail_text = _run(tmp_path, "event-log", "1", "--tail", "1")
    assert tail_text.returncode == 0, tail_text.stderr
    assert "Finished investigation" in tail_text.stdout
    assert "Started investigation" not in tail_text.stdout

    tail_json = _run(tmp_path, "event-log", "1", "--json", "--tail", "2")
    assert tail_json.returncode == 0, tail_json.stderr
    payload = json.loads(tail_json.stdout)
    assert payload["task_id"] == 1
    assert payload["event_log"] == str(_event_log_path(tmp_path, 1))
    assert [event["event"] for event in payload["events"]] == ["started", "finished"]

    details = _run(tmp_path, "show", "1", "--details")
    assert details.returncode == 0, details.stderr
    assert f"event_log: {_event_log_path(tmp_path, 1)}" in details.stdout
    assert "latest_event: " in details.stdout
    assert "Finished investigation" in details.stdout
    assert "Started investigation" not in details.stdout
    assert "evidence:" not in details.stdout


def test_checkpoint_appends_checkpoint_event_and_updates_body_from_file(tmp_path: Path) -> None:
    assert _run(tmp_path, "add", "Checkpoint task", "--body", "old body").returncode == 0
    body_path = tmp_path / "resume_body.txt"
    body_path.write_text("line one\nline two\n", encoding="utf-8")

    result = _run(
        tmp_path,
        "checkpoint",
        "1",
        "--summary",
        "Prepared resume handoff",
        "--next-action",
        "Run focused validation",
        "--evidence",
        "task_tree/files/1/checkpoint.log",
        "--body-file",
        str(body_path),
    )

    assert result.returncode == 0, result.stderr
    records = _event_records(tmp_path, 1)
    assert records[-1]["event"] == "checkpoint"
    assert records[-1]["summary"] == "Prepared resume handoff"
    assert records[-1]["next_action"] == "Run focused validation"
    assert records[-1]["evidence"] == ["task_tree/files/1/checkpoint.log"]

    details = _run(tmp_path, "show", "1", "--details")
    assert details.returncode == 0, details.stderr
    assert "body: line one" in details.stdout
    assert "line two" in details.stdout
    assert "latest_event: " in details.stdout
    assert "checkpoint: Prepared resume handoff" in details.stdout

    data = _tree_data(tmp_path)
    node = data["nodes"][0]
    assert node["body"] == "line one\nline two\n"
    assert "body_updated_at" in node["events"]
