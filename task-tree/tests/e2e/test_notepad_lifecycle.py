"""Exercise the documented notepad workflow solely through the public CLI."""
from pathlib import Path
import subprocess
import sys


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "task_tree.py"


def test_notepad_lifecycle_across_cli_invocations(tmp_path):
    def cli(*args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--tree-dir", str(tmp_path), *args],
            cwd=tmp_path,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, (args, result.stdout, result.stderr)
        assert "Unavailable:" not in result.stdout, result.stdout
        return result.stdout

    cli("add", "First task", "--set-active")
    assert "(not set)" in cli("notepad", "show")

    original = "Shared context: consult the design guide before implementation."
    cli("notepad", "replace", "--text", original)
    # Every call is a new process: readback must come from persisted state.
    assert original in cli("notepad", "show")
    assert original in cli("snapshot")
    assert original in cli("show", "1", "--details")

    cli("add", "Second task", "--set-active")
    snapshot = cli("snapshot")
    assert "Second task" in snapshot
    assert original in snapshot

    replacement = "Updated context: review the implementation handoff."
    input_file = tmp_path / "replacement.txt"
    input_file.write_text(replacement, encoding="utf-8")
    cli("notepad", "replace", "--from-file", str(input_file))
    for output in (cli("notepad", "show"), cli("snapshot"), cli("show", "2", "--details")):
        assert replacement in output
        assert original not in output

    cli("notepad", "clear")
    assert "(not set)" in cli("notepad", "show")
    snapshot = cli("snapshot")
    assert "(not set)" in snapshot
    assert replacement not in snapshot
    assert "Second task" in snapshot
    tasks = cli("show")
    assert "First task" in tasks and "Second task" in tasks
