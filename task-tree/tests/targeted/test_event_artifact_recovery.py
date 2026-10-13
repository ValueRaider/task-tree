"""Public-CLI regressions for explicit attachment and event-log recovery."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "task_tree.py"


def cli(store: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tree-dir", str(store), *args],
        cwd=store,
        text=True,
        capture_output=True,
        check=False,
    )


def tree(store: Path) -> dict:
    return json.loads((store / "tree.json").read_text(encoding="utf-8"))


def test_clear_and_reused_id_do_not_inherit_old_event_log(tmp_path: Path) -> None:
    old_add = cli(tmp_path, "add", "Old task", "--with-files", "--set-active")
    assert old_add.returncode == 0, old_add.stderr
    logged = cli(
        tmp_path, "log-event", "1", "--event", "old_evidence", "--summary", "OLD TASK EVIDENCE"
    )
    assert logged.returncode == 0, logged.stderr
    old_log = tmp_path / "files" / "1" / "events.jsonl"
    retained_bytes = old_log.read_bytes()

    cleared = cli(tmp_path, "clear")
    assert cleared.returncode == 0, cleared.stderr
    added = cli(tmp_path, "add", "New unrelated task", "--set-active")
    assert added.returncode == 0, added.stderr
    assert tree(tmp_path)["nodes"][0]["files_dir"] is None

    details = cli(tmp_path, "show", "1", "--details")
    assert details.returncode == 0, details.stderr
    assert "New unrelated task" in details.stdout
    assert "OLD TASK EVIDENCE" not in details.stdout
    assert "event_log:" not in details.stdout

    text_log = cli(tmp_path, "event-log", "1")
    assert text_log.returncode == 0, text_log.stderr
    assert "event_log: (not attached)" in text_log.stdout
    assert "(no events logged)" in text_log.stdout
    assert "OLD TASK EVIDENCE" not in text_log.stdout

    json_log = cli(tmp_path, "event-log", "1", "--json")
    assert json_log.returncode == 0, json_log.stderr
    payload = json.loads(json_log.stdout)
    assert payload == {"task_id": 1, "event_log": None, "events": []}
    assert old_log.read_bytes() == retained_bytes


def test_attach_existing_is_explicit_and_preserves_all_existing_bytes(tmp_path: Path) -> None:
    assert cli(tmp_path, "add", "Needs files").returncode == 0
    existing = tmp_path / "files" / "1"
    existing.mkdir(parents=True)
    payload = existing / "payload.bin"
    payload_bytes = b"\x00recoverable\xff\n"
    payload.write_bytes(payload_bytes)
    event_log = existing / "events.jsonl"
    event_bytes = b'{"ts":"2026-10-11T12:00:00Z","event":"recovered","summary":"prior event"}\n'
    event_log.write_bytes(event_bytes)

    refused = cli(tmp_path, "ensure-files", "1")
    assert refused.returncode == 2
    assert "artifact path collision" in refused.stderr
    assert "--attach-existing" in refused.stderr
    assert tree(tmp_path)["nodes"][0]["files_dir"] is None
    assert payload.read_bytes() == payload_bytes
    assert event_log.read_bytes() == event_bytes

    attached = cli(tmp_path, "ensure-files", "1", "--attach-existing")
    assert attached.returncode == 0, attached.stderr
    data = tree(tmp_path)
    assert data["nodes"][0]["files_dir"] == str(existing)
    assert "files_created_at" in data["nodes"][0]["events"]
    assert payload.read_bytes() == payload_bytes
    assert event_log.read_bytes() == event_bytes

    attached_again = cli(tmp_path, "ensure-files", "1", "--attach-existing")
    assert attached_again.returncode == 0, attached_again.stderr
    assert payload.read_bytes() == payload_bytes
    assert event_log.read_bytes() == event_bytes

    # Explicit attach on an absent canonical path follows ordinary creation.
    assert cli(tmp_path, "add", "New directory").returncode == 0
    created = cli(tmp_path, "ensure-files", "2", "--attach-existing")
    assert created.returncode == 0, created.stderr
    assert (tmp_path / "files" / "2").is_dir()
    assert tree(tmp_path)["nodes"][1]["files_dir"] == str(tmp_path / "files" / "2")


def test_malformed_partial_event_append_warns_but_does_not_block_tree_update(
    tmp_path: Path,
) -> None:
    assert cli(tmp_path, "add", "Valid task", "--with-files", "--set-active").returncode == 0
    event_log = tmp_path / "files" / "1" / "events.jsonl"
    complete = b'{"ts":"2026-10-11T12:00:00Z","event":"started","summary":"valid prior event"}\n'
    partial = b'{"ts":"2026-10-11T12:01:00Z","event":"checkpoint"'
    event_log.write_bytes(complete + partial)

    snapshot = cli(tmp_path, "snapshot")
    assert snapshot.returncode == 0, snapshot.stderr
    assert "Valid task" in snapshot.stdout
    assert "event log warning:" in snapshot.stdout
    assert "invalid event log JSON" in snapshot.stdout

    updated = cli(tmp_path, "update", "1", "--body", "Task state remains editable.")
    assert updated.returncode == 0, updated.stderr
    assert "Task state remains editable." in updated.stdout
    assert "event log warning:" in updated.stdout
    assert tree(tmp_path)["nodes"][0]["body"] == "Task state remains editable."

    direct = cli(tmp_path, "event-log", "1")
    assert direct.returncode == 2
    assert "invalid event log JSON" in direct.stderr
    assert event_log.read_bytes() == complete + partial


def test_unreadable_attached_event_log_warns_but_keeps_task_data(tmp_path: Path) -> None:
    assert cli(tmp_path, "add", "Still valid", "--with-files", "--set-active").returncode == 0
    event_log = tmp_path / "files" / "1" / "events.jsonl"
    event_log.mkdir()

    details = cli(tmp_path, "show", "1", "--details")
    assert details.returncode == 0, details.stderr
    assert "Still valid" in details.stdout
    assert "event log warning:" in details.stdout
    assert "unable to read event log" in details.stdout

    direct = cli(tmp_path, "event-log", "1")
    assert direct.returncode == 2
    assert "unable to read event log" in direct.stderr

    updated = cli(tmp_path, "update", "1", "--summary", "Still editable")
    assert updated.returncode == 0, updated.stderr
    assert "Still editable" in updated.stdout
    assert tree(tmp_path)["nodes"][0]["summary"] == "Still editable"
    assert event_log.is_dir()
