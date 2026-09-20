---
name: task-tree
description: Persist and inspect a project task tree so long-running work survives compaction, restarts, and session changes. Use to track subtasks, progress, and durable work breakdowns.
---

# Task Tree

The recorded tree is the authoritative plan for this project. Do not replace it
with a remembered, conversational, or ad-hoc task list. On “proceed”,
“continue”, or similar, execute the next actionable tree task unless the user
explicitly overrides it.

Use `scripts/task_tree.py` for every read and write; it is the task-tree API.
If its CLI lacks an operation, inspect and extend it deliberately rather than
editing the JSON directly. Before using an unfamiliar mutation flag, consult
`--help` or the argument parser—do not guess.

The default tree is `./task_tree/tree.json`. Put `--tree-file PATH` before the
command to select another tree. That selected file’s parent owns its `files/`,
`shared/`, and lock artifacts. The runtime uses a filesystem lock and atomic
writes; always use the script so concurrent changes serialize safely. The
current parent-owned ordering schema never auto-migrates legacy trees; see
[schema.md](references/schema.md) and [migration.md](references/migration.md)
if it reports one.

## Inspecting State

For a bare `$task-tree`, a request to check state, and normal post-mutation
output, run the compact snapshot:

```bash
python .agents/skills/task-tree/scripts/task_tree.py snapshot
```

It shows the active task in full plus only orientation titles: its parent,
previous and next siblings, and the next task after its subtree. Do not print
the full tree unless the user asks or a narrow command cannot answer the
question. Use `show <id> --details` for one node and `show` for the full tree.
Use `--full-tree` after a mutation only when it is genuinely needed.

Before choosing work, inspect the active task and/or run `next`. Keep one
actionable task active when there is a clear focus. Do not jump to a sibling
while the current active task, including a terminal one, has unfinished
children unless the user explicitly says to override tree order. Never manually
activate a terminal task; an automatic `return_to_id` continuation may
intentionally restore focus to one for review, reopening, or traversal.

## Creating and Placing Work

Tasks are small, concrete units with a summary and body. A parent is a real
task, not a heading: it states purpose, gates, closeout criteria, and handoff.
Any task may receive children; parent/child expresses relationship, not type.
Adding children does not make the parent complete or non-actionable.
The frontier comprises tasks without children; it does not determine their
status, readiness, or whether a parent has work of its own.

For substantive work, read [task-sizing.md](references/task-sizing.md) before
creating or starting it, and again when scope expands. Routine inspection,
navigation, and status changes do not need that assessment.

To place new work, start with the compact snapshot. The active task’s details,
its parent, and nearby sibling titles normally provide enough context:

- Work that directly advances the active task belongs beneath it.
- A distinct track toward the active task’s parent-level outcome is a sibling
  under that parent.
- When a visible sibling or parent clearly owns it, place it in that subtree.
- Otherwise, make a new root task.

Read `show <id> --details` only when a body or closeout criteria are required
to resolve ownership. Ask the user only if that focused inspection remains
ambiguous. Titles route initially; they are not proof of ownership. For ordered
insertion rules, read [execution-order.md](references/execution-order.md).

### Temporary switches

When the user clearly asks to *temporarily* switch to work outside the current
subtree, or otherwise clearly describes an interruption, create and activate
the new task with `--return-to <current-id> --set-active`. Parentage and return
continuation are independent: urgent work may belong under another workstream
while returning focus to the interrupted task after its whole subtree is
terminal.

Do not set a return pointer for an explicit permanent reprioritization. If the
request does not establish whether the switch is temporary, ask whether the
user wants to resume the current task afterward. See
[execution-order.md](references/execution-order.md#temporary-priority-work-and-return_to)
for firing and validity rules.

## Task Records, Artifacts, and Handoffs

The task body is the plan and resume handoff: scope, instructions, gates,
closeout criteria, and the next owner’s context. Update it when that plan or
handoff changes—not merely to store findings. Put reports, diagnostics,
transcripts, drafts, and other outputs in `task_tree/files/<task-id>/`; run
`ensure-files <id>` before writing when needed. Shared effort material belongs
in `task_tree/shared/`, never `/tmp` when a task artifact folder is available.

Use `events.jsonl` in the task artifact folder for short factual,
artifact-linked progress/resume pointers, not transcripts. Event timestamps
and the detailed artifact contract are in
[commands.md](references/commands.md#task-data-and-artifacts).

Before compaction, restart, or handoff on nontrivial active work:

1. Put a compact handoff in the current task body: completed state, exact next
   action, blockers/caveats, and only material file paths.
2. If a child is the clearer next action, create or update that child and put
   the handoff there.
3. Make the true resume target active.
4. For cross-role work, state `owner_role`, `allowed_actions`, and
   `forbidden_actions`. A review task must not silently authorize its reviewer
   to implement a production repair.

`notes/` is overflow or backup, never the sole compaction handoff. A completed
task body may concisely state the result and link an artifact, but should not
become the full report.

## Lifecycle and Safety

Set a branch parent `in_progress` when starting it. Work children in tree
order, then review the parent after all its direct children are terminal. Do
not complete it merely because children exist. The closeout-review procedure,
including `closeout_reviewed`, is in [closeout.md](references/closeout.md).

Do not invent progress, overwrite the backing file outside the script, or keep
a separate task list. Warn before deleting a task with children; never silently
delete a subtree. Encode real gates in the tree’s status, ordering, and body—do
not rely on conversation memory to remember that seemingly actionable work is
deferred.

## Git-Backed Work

For a usable Git repository, when neither the user nor project rules prohibit
commits, prefer small durable scoped commits over an accumulating working-tree
diff. A task checkpoint and a Git checkpoint serve different purposes. Never
stage or commit unrelated dirty files.

Before multi-commit work, branch changes, or merging a task subtree, read
[git-backed-work.md](references/git-backed-work.md).

## Command Reference

Use these everyday operations; all other commands and their exact output modes
are in [commands.md](references/commands.md).

```bash
# Inspect, find the next task, and inspect one task.
python .agents/skills/task-tree/scripts/task_tree.py snapshot
python .agents/skills/task-tree/scripts/task_tree.py next
python .agents/skills/task-tree/scripts/task_tree.py show 2 --details

# Create work, change it, or activate it.
python .agents/skills/task-tree/scripts/task_tree.py add "Investigate bug X" --parent 1
python .agents/skills/task-tree/scripts/task_tree.py update 2 --status in_progress
python .agents/skills/task-tree/scripts/task_tree.py set-active 2
```

`not_started` and `in_progress` are actionable; `completed`, `aborted`, and
`impossible` are terminal. See the command reference for task mutation,
reordering, querying, events, artifacts, deletion, and reset/clear semantics.

## Design Notes

This implementation favors transparent, durable JSON storage, a CLI API,
explicit artifact folders, filesystem locking with atomic writes, and
lifecycle timestamps over a more sophisticated hidden system.
