"""Behavioral regressions for ordinary managed-note files and hard links."""

import os
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "task_tree.py"


def run_cli(tmp_path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--tree-dir", str(tmp_path), *args],
        capture_output=True,
        text=True,
    )


def managed_note(text):
    return f'<!-- task-tree managed notepad: "tree.json" -->\n{text}'


def test_existing_managed_note_can_be_read_replaced_and_cleared(tmp_path):
    assert run_cli(tmp_path, "add", "Example", "--set-active").returncode == 0
    shared = tmp_path / "shared"
    shared.mkdir()
    note = shared / ".task-tree-notepad.md"
    unrelated = shared / "other.md"
    note.write_text(managed_note("Retain this note."), encoding="utf-8")
    unrelated.write_text("Leave unrelated context alone.", encoding="utf-8")

    for args in [("notepad", "show"), ("snapshot",)]:
        result = run_cli(tmp_path, *args)
        assert result.returncode == 0, result.stderr
        assert "Retain this note." in result.stdout, result.stdout
        assert "Unavailable" not in result.stdout

    result = run_cli(tmp_path, "notepad", "replace", "--text", "Updated note.")
    assert result.returncode == 0, result.stderr
    assert "Updated note." in run_cli(tmp_path, "notepad", "show").stdout
    result = run_cli(tmp_path, "notepad", "clear")
    assert result.returncode == 0, result.stderr
    assert not note.exists()
    assert unrelated.read_text(encoding="utf-8") == "Leave unrelated context alone."


def test_readable_hard_link_note_is_accepted_and_unlinked_peer_is_unchanged(tmp_path):
    assert run_cli(tmp_path, "add", "Example").returncode == 0
    shared = tmp_path / "shared"
    shared.mkdir()
    note = shared / ".task-tree-notepad.md"
    note.write_text(managed_note("Original linked note."), encoding="utf-8")
    peer = tmp_path / "note-peer.md"
    os.link(note, peer)
    original_bytes = note.read_bytes()

    result = run_cli(tmp_path, "notepad", "show")
    assert result.returncode == 0, result.stderr
    assert "Original linked note." in result.stdout

    result = run_cli(tmp_path, "notepad", "replace", "--text", "Replaced note.")
    assert result.returncode == 0, result.stderr
    assert "Replaced note." in note.read_text(encoding="utf-8")
    assert peer.read_bytes() == original_bytes

    result = run_cli(tmp_path, "notepad", "clear")
    assert result.returncode == 0, result.stderr
    assert not note.exists()
    assert peer.read_bytes() == original_bytes
