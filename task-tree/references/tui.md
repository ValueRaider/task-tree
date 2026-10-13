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

## Text search

Press `/` to open the search command bar. After 500 ms without further typing,
deletion, or pasting, search automatically updates matches and previews a matching
task while keeping focus in the input. Each edit restarts this delay, so rapid
edits trigger only one search. Every preview searches at or after the task
selected when `/` was opened, rather than advancing from the previous preview.
If there are no matches or the query is empty, the cursor returns to that
original task.

Enter applies the current input immediately, without waiting for the delay, and
returns to tree navigation. Escape cancels pending search and restores the
previous search, selection, and branch expansion. Clearing the input removes
match highlighting after the same delay; Enter clears it immediately. Opening
`/` again selects the previous query for replacement or editing. Queries are
plain, literal text, not regexes, and special characters are not treated as
modifiers.

Press `n` for the next matching task or `N` (Shift+N) for the previous one.
Matches follow depth-first tree order and wrap around. Collapsed descendants
are included, and jumping to one expands its ancestors. Matching task labels
are emphasized; the status line reports the match position/count or no matches.
Search navigates the existing tree rather than hiding tasks.

Outside search input, press `s` to configure search. The bottom command bar
replaces the normal controls with the current settings and these toggles:

| Key | Setting |
| --- | --- |
| `c` | Toggle case-sensitive / case-insensitive matching |
| `b` | Include task bodies as well as summaries |
| `1` | Ignore `completed` tasks |
| `2` | Ignore `aborted` tasks |
| `3` | Ignore `impossible` tasks |
| `4` | Ignore `not_started` tasks |
| `5` | Ignore `in_progress` tasks |

Each state toggle shows `on` when that state is ignored. Escape, Enter, or `s`
returns to navigation, retaining settings and recomputing an existing search
without jumping to another task. Normal navigation, move, reload, and quit keys
do not run while configuring search; while entering a query, letters such as
`s`, `q`, and `m` are ordinary text.

Defaults are case-sensitive, summaries only, and no ignored states. Preferences
last for the TUI session, including reloads; they do not change the stored tree.
Ignored parents remain visible and do not exclude eligible descendants. Body
search reads the stored body text, not artifact file contents. Finish or cancel
an active move/drag before entering search or navigating search matches.

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
