# Interactive Terminal Viewer

The optional TUI requires Textual:

```bash
python -m pip install textual
python .agents/skills/task-tree/scripts/task_tree.py tui
```

For a non-default tree, place the global option before the command:

```bash
python .agents/skills/task-tree/scripts/task_tree.py \
  --tree-dir path/to/store tui
```

Use Up/Down or the mouse to select a task. Right expands it; Left collapses it,
or moves to its parent when it is already collapsed or has no children. Space
or the expander toggles the subtree. Press `r` to reload and `q` to quit.

The stacking breakpoint is **90 + 8 × active task depth** terminal columns.
A root task has depth 0; no active task uses the 90-column base. Below the
breakpoint the tree appears above the task-details/notepad pane; at or above it
they remain side by side. Depth comes from the durable active task’s ancestors,
not the selected task or expanded subtree. Expanding/collapsing nodes and
changing selection therefore do not change the breakpoint. It updates on resize
and when refreshed tree data changes active ancestry, without rebuilding the
tree merely for a resize. In stacked mode the tree gets 45% of the available
main height and the details pane gets 55%.

The details pane (right-hand or below the tree) scrolls with the mouse wheel. Press `Tab` to focus
it, then use Up/Down, PageUp/PageDown, Home, or End. Selecting another task
resets the details to the top. A labelled **Tree-wide notepad** section appears
beneath the selected task print-out inside this same details scroll pane,
not in the tree pane. With short details, spare space above the note positions it
at the bottom of the pane; with long details, it follows them in the scroll flow.
It stays shared when selection changes; `r` reloads both
the tree and note. Long task details may require scrolling to reach it. The note
is displayed literally, with explicit missing/error status, including when the
tree has no tasks. On startup, the viewer reveals the branch to
the active task and expands that task when it has children.

## Relocate a task

Click and drag a task to move it. The valid durable task under the pointer is
the candidate destination. Within that candidate's actual text, dropping on
the left half places the source immediately after it; dropping on the right
half appends the source as a child. The source's original click position does
not affect this choice.

For a no-button move, select a task and press `m`. Move the pointer over a
candidate's text and use the same midpoint rule. Release a held drag or click
in move mode to place it. Press Escape, press `m` again, or release outside a
valid destination to cancel.

Leaf tasks reserve the same two-cell expander width as expandable siblings so
task text stays aligned. The placement preview restyles source and candidate
labels without changing layout or expansion.

Press `U` or `Ctrl+Z` to undo the latest TUI relocation when it is still safe.
Undo is session-local, and reload clears it. Its stale-change guard uses a
per-move opaque marker that changes on every relocation, not a wall-clock
value. Human `moved_at` timestamps remain actual timestamps; they are not advanced
into the future to simulate identity. Capture and compare the marker under the
normal store lock. A newer move invalidates an earlier receipt even within the
same second and same parent; no undo journal or schema version is introduced. Relocations use the normal locked
store rather than editing JSON directly.

## Compact detail rendering

Details list at most ten artifact paths relative to the task files directory
and report omitted paths. They show only first-level children—the first three,
then an omitted count—and never grandchildren. A non-root parent is rendered
in compact task syntax and may show `<< ACTIVE`; roots show `Parent: None`.
