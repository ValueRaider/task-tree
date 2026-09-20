# Command Reference

Run all commands through `python .agents/skills/task-tree/scripts/task_tree.py`.
The compact snapshot is the default output for mutations; use `--full-tree`
only when the full post-mutation tree is needed.

## Read and inspect

```bash
# Compact or machine-readable state.
python .agents/skills/task-tree/scripts/task_tree.py snapshot
python .agents/skills/task-tree/scripts/task_tree.py snapshot --json

# Select another tree for one command.
python .agents/skills/task-tree/scripts/task_tree.py --tree-file path/to/tree.json snapshot

# Full tree, one task, or direct children.
python .agents/skills/task-tree/scripts/task_tree.py show
python .agents/skills/task-tree/scripts/task_tree.py show 2 --details
python .agents/skills/task-tree/scripts/task_tree.py children 2
python .agents/skills/task-tree/scripts/task_tree.py children 2 --details
python .agents/skills/task-tree/scripts/task_tree.py children 2 --json

# Find work.
python .agents/skills/task-tree/scripts/task_tree.py list --status in_progress
python .agents/skills/task-tree/scripts/task_tree.py query --status completed --since-days 2 --event status_changed_at
python .agents/skills/task-tree/scripts/task_tree.py query --status completed --since-days 2 --contains "Centene" --event status_changed_at --details
python .agents/skills/task-tree/scripts/task_tree.py next
python .agents/skills/task-tree/scripts/task_tree.py next 156
python .agents/skills/task-tree/scripts/task_tree.py path 2
python .agents/skills/task-tree/scripts/task_tree.py shared-dir
```

Details list at most ten artifact paths relative to the task files directory
and report omitted paths. They show only first-level children (first three,
then an omitted count), never grandchildren. A non-root parent is rendered in
compact task syntax and may show `<< ACTIVE`; roots show `Parent: None`.

## Create and update

```bash
# Roots, children, details, and artifact folders.
python .agents/skills/task-tree/scripts/task_tree.py add "Port task-tree to Codex" --body "Create a durable Codex-native version."
python .agents/skills/task-tree/scripts/task_tree.py add "Port task-tree to Codex" --details
python .agents/skills/task-tree/scripts/task_tree.py add "Inspect session logs" --with-files
python .agents/skills/task-tree/scripts/task_tree.py add "Implement first iteration" --parent 1
python .agents/skills/task-tree/scripts/task_tree.py ensure-files 2

# Temporary priority work and its continuation.
python .agents/skills/task-tree/scripts/task_tree.py add "Investigate urgent regression" --return-to 654 --set-active
python .agents/skills/task-tree/scripts/task_tree.py update 679 --return-to 654
python .agents/skills/task-tree/scripts/task_tree.py update 679 --clear-return-to

# Change a record or its active focus.
python .agents/skills/task-tree/scripts/task_tree.py update 2 --status in_progress
python .agents/skills/task-tree/scripts/task_tree.py update 2 --summary "Implement JSON-backed first iteration"
python .agents/skills/task-tree/scripts/task_tree.py update 2 --closeout-reviewed true
# Body files are UTF-8 and support long or multiline bodies.
python .agents/skills/task-tree/scripts/task_tree.py update 2 --body-file task_tree/files/2/body.txt
python .agents/skills/task-tree/scripts/task_tree.py set-active 2
```

## Order and structure

```bash
python .agents/skills/task-tree/scripts/task_tree.py move 3 --parent 2
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --first
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --last
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --before 4
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --after 4
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --before-first-pending
```

`reorder` changes only sibling order. `--before` and `--after` require a target
with the same parent; pending means `not_started` or `in_progress`. See
[execution-order.md](execution-order.md) when placement also requires a focus
change or a prerequisite insertion before the active task.

## Progress events and task data

```bash
python .agents/skills/task-tree/scripts/task_tree.py log-event 2 \
  --event repair_completed \
  --summary "Fixed section binding regression" \
  --evidence task_tree/files/2/repair.log \
  --next-action "Re-run focused validation"
python .agents/skills/task-tree/scripts/task_tree.py checkpoint 2 \
  --summary "Prepared resume handoff after focused validation" \
  --next-action "Inspect the regenerated output set" \
  --body-file task_tree/files/2/resume_body.txt
python .agents/skills/task-tree/scripts/task_tree.py event-log 2
python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --tail 10
python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --json --tail 20
```

Status values are `not_started`, `in_progress`, `completed`, `aborted`, and
`impossible`. Task lifecycle timestamps include `created_at`, `activated_at`,
`status_changed_at`, `summary_updated_at`, `body_updated_at`, `moved_at`,
`files_created_at`, `files_pruned_at`, and `last_mutated_at`; inspect them with
`show <id> --details`. These timestamps are distinct from the append-only
progress-event log.

## Task data and artifacts

Tree data lives under `./task_tree/`; shared artifacts are in `shared/`,
per-task artifacts in `files/<task-id>/`, and progress events in
`files/<task-id>/events.jsonl`. Artifact folders are explicit and never
automatically deleted.

## Deletion and reset

```bash
# delete also removes every deleted task's artifact folder
python .agents/skills/task-tree/scripts/task_tree.py delete 3

# remove only one task's artifacts, or reset the whole tree and task files
python .agents/skills/task-tree/scripts/task_tree.py prune-files 3
python .agents/skills/task-tree/scripts/task_tree.py reset

# clear supports optional pruning or removal of the backing file
python .agents/skills/task-tree/scripts/task_tree.py clear --prune-files --prune-shared --drop-file
```

`delete <id>` removes its subtree and task artifact directories. `prune-files`
does not delete the task. `reset` clears the entire tree and `task_tree/files/`;
use `clear` only when its more specific cleanup behavior is requested.

## Operator summary

`snapshot`, `show`, `list`, `query`, `children`, `next`, `path`, and
`shared-dir` read task state. `add`, `update`, `set-active`, `move`, `reorder`,
`ensure-files`, `log-event`, `checkpoint`, `delete`, `prune-files`, `reset`,
and `clear` mutate it. Consult command `--help` for the complete accepted
arguments before using an unfamiliar mutation.
