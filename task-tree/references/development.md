# Task-tree development

This is maintenance guidance, not a user workflow or a separate runtime API.

## Runtime modules and dependencies

The command-line runtime is implemented by four modules under `scripts/`:

- `task_tree.py` owns argument parsing, store locking, command behavior, and
  lifecycle operations.
- `task_tree_schema.py` owns validation and initialization of persisted tree
  data.
- `task_tree_notepad.py` owns bounded tree-wide note I/O.
- `json_format.py` owns shared JSON rendering.

These CLI modules use the Python standard library; there are no third-party
runtime dependencies for CLI-only use. `task_tree_tui.py` is the optional
interactive viewer and requires Textual and Rich. Install Textual to get its
Rich dependency:

```bash
python -m pip install textual
```

## Tests

The suite uses pytest. UI tests run when Textual is installed and are skipped
otherwise; the CLI regressions remain independently collected. From the
repository root, run the full suite:

```bash
python -m pytest .agents/skills/task-tree/tests
```

For a CLI-only test environment, install pytest but not Textual or Rich, then
run the same command. This exercises non-UI tests and reports optional UI
modules as skipped. For a full UI-capable suite, install Textual and run the
same command. To focus on the interactive viewer tests:

```bash
python -m pytest \
  .agents/skills/task-tree/tests/test_task_tree_tui.py \
  .agents/skills/task-tree/tests/test_task_tree_tui_drag.py \
  .agents/skills/task-tree/tests/test_task_tree_tui_move_mode.py \
  .agents/skills/task-tree/tests/test_task_tree_tui_undo.py \
  .agents/skills/task-tree/tests/targeted/test_stale_move_marker_undo.py
```

Use the actual CLI entry point for smoke checks:

```bash
python .agents/skills/task-tree/scripts/task_tree.py --help
```

To qualify the deployed four-module runtime bundle and its persisted notepad
lifecycle through fresh CLI processes, run:

```bash
python -m pytest \
  .agents/skills/task-tree/tests/test_task_tree_runtime_deployment.py \
  .agents/skills/task-tree/tests/e2e/test_notepad_lifecycle.py
```
