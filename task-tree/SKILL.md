---
name: task-tree
description: Persist and inspect a tree of tasks in the project so long-running work can survive compaction, restarts, and session changes. Use when Codex needs to track subtasks, mark progress, show what is active, or maintain a durable work breakdown for a large task.
---

# Task Tree

## Overview

Maintain a persistent tree of tasks in the current project. Use it for long-running or multi-session work where an external task record is more reliable than conversational memory alone.

When this skill is active for a project, the task tree is the default authoritative plan. Do not substitute a remembered, conversational, or ad hoc plan for the recorded tree. If the user says "proceed", "continue", or similar, execute the next actionable pending task from the tree unless the user explicitly overrides it.

The default backing store is `./task_tree/tree.json`. `--tree-file PATH`
selects another JSON file for one invocation. Place this global option before
the command, for example:

```bash
python .agents/skills/task-tree/scripts/task_tree.py \
  --tree-file path/to/tree.json snapshot
```

The selected JSON file's parent directory also owns that tree's `files/`,
`shared/`, and lock artifacts.

The current persisted schema stores ordered child IDs on their parent and root
order in a top-level list; it does not store child-owned parent/order fields.
See [references/schema.md](references/schema.md). The runtime diagnoses a
recognizable legacy tree but never auto-migrates it; use the explicit procedure
in [references/migration.md](references/migration.md).

Supporting folders:

- shared artifacts: `./task_tree/shared/`
- per-task artifacts: `./task_tree/files/<task-id>/`

## Default Display

When the user invokes `$task-tree` without any extra prompt or asks only to
print/check task-tree state, do **not** print the full tree by default. Show the
compact status snapshot instead:

```bash
python .agents/skills/task-tree/scripts/task_tree.py snapshot
```

The snapshot shows the active task in full. For orientation, it shows only the
titles of the active task's parent, previous sibling, next sibling, and the
next task after the current subtree when those tasks exist. Finding the latter
may require climbing through multiple ancestors. The snapshot does not expand
those nearby tasks or repeat the full ancestry path. Use the full tree only
when the user explicitly asks for it or when a narrow command cannot answer the
question.

Mutation commands also print this compact snapshot by default. Use
`--full-tree` only when the post-mutation full tree is genuinely needed; use
`--details` on commands that support it when the affected node, rather than the
active-task context, is what needs review.

## Workflow

1. Use the script under `scripts/task_tree.py` for all reads and writes.
2. Treat `scripts/task_tree.py` as the task-tree API. When the existing CLI
   does not expose the exact operation needed, inspect or extend the script with
   a focused command, then use that command.
   Before using an unverified local-script mutation option, check the command's
   `--help` output or source parser instead of guessing a plausible flag.
3. Treat the tree as the default authoritative plan. Before choosing what to do next, inspect the active task and/or run `next`; do not jump to a sibling while the active task has unfinished child tasks unless the user explicitly says to skip them.
5. Prefer small, concrete tasks and summaries. Before creating or activating
   substantive work, apply the conditional sizing guidance below.
6. Keep one task marked active when there is a clear current focus. Direct
   `set-active` selection is limited to actionable tasks (`not_started` or
   `in_progress`). A `return_to_id` continuation may deliberately restore focus
   to a terminal task so its branch can be reviewed, reopened, or traversed
   from that point.
7. After any mutation, show the compact snapshot by default. Show the affected
   node with `--details` or the full tree with `--full-tree` only when that
   additional output is needed.
8. Warn before deleting a task that has children.
9. Use `shared/` for materials that belong to the broader effort, and `files/<task-id>/` for task-owned artifacts.
10. The script uses a filesystem lock on the tree file, so multiple agents can safely serialize updates to the same tree.
11. Each task records event timestamps so the tree can preserve when important changes happened across compaction and resume.
12. Treat the task body as the task's plan: scope, instructions, gates, and
    resume handoff. Modify the body when the plan/handoff changes, not merely to
    store reports, transcripts, progress notes, or detailed findings.
13. Put task outputs, reports, transcripts, drafts, diagnostics, and other
    progress artifacts in `./task_tree/files/<task-id>/`. If the folder does not
    exist, run `ensure-files <task-id>` before writing the artifact.
14. Use the per-task append-only event log at
    `./task_tree/files/<task-id>/events.jsonl` for compact progress/resume
    pointers. Keep event entries short, factual, and artifact-linked; do not use
    them as transcripts.

## Substantive Work Sizing

Task sizing here manages context-window workload, not worker capability.
Before creating or starting substantive work, and when its scope expands, read
[references/task-sizing.md](references/task-sizing.md). This applies to all
kinds of work, including work on a task that already has children. Routine
display, navigation, and status changes do not require the reference.

## Git-Backed Task Boundaries

When the project is a usable Git repository and neither the user nor project
instructions prohibit commits, prefer durable scoped commits over a growing
working-tree diff. A task-tree checkpoint does not replace a Git checkpoint,
and a commit does not establish that a task is complete. Never stage or commit
unrelated dirty files.

Before starting Git-backed work likely to need multiple coherent commits,
before changing branches, or before merging a task subtree, read
[references/git-backed-work.md](references/git-backed-work.md). It defines the
short-lived branch workflow, checkpoint criteria, shared-working-tree
ownership, validation, and closeout records.

## Parent / Child Behavior

Any task may gain children directly; no conversion is required. Parent and
child describe relationships, not different task types. The frontier is the
set of tasks currently at the ends of branches (tasks without children).
Adding children moves that branch's frontier to those children. This position
does not determine task status, readiness, or whether a task with children
still has work of its own to do.

Parent tasks are real tasks, not just headings. Use them to state the purpose,
gates, closeout criteria, and handoff for their child work.

For the ordering data model, the distinction between ordinary and explicitly
relative next-task traversal, and the exact procedure for
inserting a new child before an active middle child, see
[references/execution-order.md](references/execution-order.md).

For a temporary priority interruption, `return_to_id` can override ordinary
post-completion traversal without changing hierarchy or sibling order. The
return fires once, when the focused task crosses into a terminal state and its
subtree has no actionable work. See
[references/execution-order.md](references/execution-order.md#temporary-priority-work-and-return-to).

Normal lifecycle:

1. Set the parent `in_progress` when starting that branch.
2. Work its children in tree order.
3. Do not mark the parent complete merely because the children exist; complete
   it only after child outputs have been reviewed/processed and the parent's
   closeout criteria are satisfied.
4. After the last child is completed, revisiting the parent for closeout is
   expected and correct. Re-read the parent's summary and body at that point:
   decide whether the parent is now complete, still has a real closeout action,
   needs its stale planning wording updated, or has become obsolete. Do not
   keep working from the parent's old wording without checking whether its
   children have already satisfied it.
5. This closeout review is automatic. When a parent is still actionable
   (`not_started` or `in_progress`), has children, and all direct children are
   terminal (`completed`, `aborted`, or `impossible`), perform the closeout
   review before advancing outside that parent branch. Do not wait for the user
   to ask whether the parent is still relevant.
6. Each task has a `closeout_reviewed` boolean flag. It is normally `false`.
   Set it to `true` only after reading the parent and deciding that the
   completed/aborted/impossible direct children have been processed. If the
   closeout decision is "this parent is done", mark the parent terminal. If the
   parent remains actionable after review, set `closeout_reviewed: true` so the
   closeout-due warning is not repeated; because the parent is still actionable,
   `next` may still surface it as ordinary unfinished work. Adding, moving,
   deleting, or changing the status of a child invalidates the parent's closeout
   flag.

Therefore, if an active child is completed and no pending children remain under
that parent, the next actionable task may be the parent itself. Do not treat this
as an error. If a parent must not be worked yet, encode that in the tree:

- do not leave it `in_progress`/actionable;
- place it after the work that gates it;
- state the gate clearly in its body; and
- set the active pointer to the true next actionable task.

Do not rely on conversation memory to remember that an `in_progress` parent is
actually deferred. The tree status and ordering must represent that.

## Compaction / Resume Rule

The whole point of `task-tree` is to keep the important resume state **in the tree itself**.

Before compaction, restart, or handoff on any nontrivial active work:

1. Update the **current task body** with a compact resume handoff that includes:
   - current state
   - what was completed
   - the exact next action
   - important blockers / caveats
   - key files only when they matter for the next step
   - when the handoff crosses roles, explicit `owner_role`, `allowed_actions`,
     and `forbidden_actions`
2. If the next action is clearer as a child task, create or update that **next task** and put the resume handoff there.
3. Set the true resume target task as **active**.
4. Make sure the tree itself tells the next agent what to do, without requiring conversational memory.
5. Use a note in `notes/` only as **overflow or backup**, not as the primary handoff.

If a review/diagnostic task creates a production repair handoff, the task body
must not authorize the reviewer to implement the repair directly. State the
production owner and any forbidden direct edits explicitly.

Default preference:
- **task body / active next task** = primary handoff
- `notes/` = optional overflow only

## Common Commands

Default compact task status snapshot:

```bash
python .agents/skills/task-tree/scripts/task_tree.py snapshot
```

Machine-readable status snapshot:

```bash
python .agents/skills/task-tree/scripts/task_tree.py snapshot --json
```

Run any command against an explicitly selected tree JSON file:

```bash
python .agents/skills/task-tree/scripts/task_tree.py \
  --tree-file path/to/tree.json snapshot
```

Show the full tree only when needed:

```bash
python .agents/skills/task-tree/scripts/task_tree.py show
```

Explicitly show the full tree after a mutation:

```bash
python .agents/skills/task-tree/scripts/task_tree.py update 2 --status completed --full-tree
```

Show a node with details:

```bash
python .agents/skills/task-tree/scripts/task_tree.py show 2 --details
```

Detailed output includes the task artifact files as sorted paths relative to
its `files_dir`. It shows at most ten paths and reports how many additional
files were omitted, so a large artifact folder does not swamp the task record.
It also shows only the first level of child tasks: the first three children in
tree order with state, ID, and title, followed by the omitted-child count when
more exist. It never recursively expands grandchildren in node details.
For a non-root task, details use the same compact task syntax as child entries,
for example `Parent: [ ] #2 Parent title`, including `<< ACTIVE` when applicable.
Root tasks show `Parent: None`.

Show direct children of a node:

```bash
python .agents/skills/task-tree/scripts/task_tree.py children 2
python .agents/skills/task-tree/scripts/task_tree.py children 2 --details
python .agents/skills/task-tree/scripts/task_tree.py children 2 --json
```

Create a temporary priority task that returns focus to task `654` after its
whole subtree finishes:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add \
  "Investigate urgent regression" --return-to 654 --set-active
```

Set or clear the continuation on an existing task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py update 679 --return-to 654
python .agents/skills/task-tree/scripts/task_tree.py update 679 --clear-return-to
```

List tasks by status:

```bash
python .agents/skills/task-tree/scripts/task_tree.py list --status in_progress
```

Query tasks by status/text and recent event time:

```bash
python .agents/skills/task-tree/scripts/task_tree.py query --status completed --since-days 2 --event status_changed_at
python .agents/skills/task-tree/scripts/task_tree.py query --status completed --since-days 2 --contains "Centene" --event status_changed_at --details
```

Suggest the next task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py next
```

Suggest the next task relative to a specific task without changing the active
pointer:

```bash
python .agents/skills/task-tree/scripts/task_tree.py next 156
```

Show the shared artifact folder:

```bash
python .agents/skills/task-tree/scripts/task_tree.py shared-dir
```

Create a root task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add "Port task-tree to Codex" --body "Create a durable Codex-native version."
```

Create a task and print the newly-created task details instead of the full tree:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add "Port task-tree to Codex" --details
```

Create a task with its own artifact folder:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add "Inspect session logs" --with-files
```

Create a task folder later:

```bash
python .agents/skills/task-tree/scripts/task_tree.py ensure-files 2
```

Create a child task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add "Implement first iteration" --parent 1
```

Update status or text:

```bash
python .agents/skills/task-tree/scripts/task_tree.py update 2 --status in_progress
python .agents/skills/task-tree/scripts/task_tree.py update 2 --summary "Implement JSON-backed first iteration"
python .agents/skills/task-tree/scripts/task_tree.py update 2 --closeout-reviewed true
```

Update a long or multiline task body from a UTF-8 file:

```bash
python .agents/skills/task-tree/scripts/task_tree.py update 2 --body-file task_tree/files/2/body.txt
```

Append a compact progress event:

```bash
python .agents/skills/task-tree/scripts/task_tree.py log-event 2 \
  --event repair_completed \
  --summary "Fixed section binding regression" \
  --evidence task_tree/files/2/repair.log \
  --next-action "Re-run focused validation"
```

Append a checkpoint event and optionally refresh the task body from a file:

```bash
python .agents/skills/task-tree/scripts/task_tree.py checkpoint 2 \
  --summary "Prepared resume handoff after focused validation" \
  --next-action "Inspect the regenerated output set" \
  --body-file task_tree/files/2/resume_body.txt
```

Inspect the append-only event log:

```bash
python .agents/skills/task-tree/scripts/task_tree.py event-log 2
python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --tail 10
python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --json --tail 20
```

Set the active task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py set-active 2
```

Show a path from root:

```bash
python .agents/skills/task-tree/scripts/task_tree.py path 2
```

Move a task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py move 3 --parent 2
```

Reorder a task among its siblings:

```bash
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --last
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --first
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --before 4
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --after 4
python .agents/skills/task-tree/scripts/task_tree.py reorder 3 --before-first-pending
```

Delete a task and its artifact folder:

```bash
python .agents/skills/task-tree/scripts/task_tree.py delete 3
```

Delete a task artifact folder without deleting the task:

```bash
python .agents/skills/task-tree/scripts/task_tree.py prune-files 3
```

Reset the whole task tree and delete per-task artifact folders:

```bash
python .agents/skills/task-tree/scripts/task_tree.py reset
```

## Status Values

- `not_started`
- `in_progress`
- `completed`
- `aborted`
- `impossible`

## Event Timestamps

Tasks can record distinct timestamps for different lifecycle events, including:

- `created_at`
- `activated_at`
- `status_changed_at`
- `summary_updated_at`
- `body_updated_at`
- `moved_at`
- `files_created_at`
- `files_pruned_at`
- `last_mutated_at`

Use `show <id> --details` to inspect them.

These lifecycle timestamps are separate from the append-only progress log in
`task_tree/files/<task-id>/events.jsonl`.

## Artifact Layout

- Tree files stay under `./task_tree/`
- Shared artifacts go under `./task_tree/shared/`
- Task-specific artifacts go under `./task_tree/files/<task-id>/`
- Progress-event logs go under `./task_tree/files/<task-id>/events.jsonl`

Task artifact folders are created explicitly and are never deleted automatically.

Use task artifact folders for task-owned outputs. The task body remains the
plan/resume surface. A completed task body may summarize the result and point to
files such as `task_tree/files/<task-id>/review.md`, but should not be rewritten
with a full report unless the report is itself the new plan or essential compact
handoff.

## Operators

- `snapshot` shows active task details plus previous/next sibling and next
  actionable task; running the script with no command does the same
- `show [node_id] [--details]` renders the tree or a specific node
- `list [--status ...]` gives a flat filtered view
- `query [--status ...] [--contains ...] [--event ...] [--since-days ...] [--details]` filters tasks by text and event time
- `reorder <id> --first|--before <sibling-id>|--after <sibling-id>|--before-first-pending|--last` changes a task's display/next-task order among siblings; pending means `in_progress` or `not_started`
- `next` suggests the next likely actionable task
- `ensure-files <id>` creates a per-task artifact directory
- `log-event <id> --event ... --summary ...` appends a compact JSONL progress event
- `event-log <id> [--tail N] [--json]` shows a task's append-only event log
- `checkpoint <id> --summary ... [--body-file ...]` appends a checkpoint event and can refresh the task body explicitly from a file
- `delete <id>` deletes a task/subtree and always deletes each deleted task's artifact directory
- `children <id> [--details] [--json]` lists the direct child tasks of a node
- `prune-files <id>` deletes a per-task artifact directory without deleting the task
- `reset` clears the whole tree and deletes `task_tree/files/`
- `clear [--prune-files] [--prune-shared] [--drop-file]` clears the tree; use `reset` when the user asks to reset or clean up the tree

## Constraints

- Do not keep a separate ad hoc task list when this skill is being used.
- Do not treat conversational memory as higher authority than the tree. When uncertain, inspect `active`, `show`, and `next` before acting.
- Do not manually set a completed, aborted, or impossible task active.
- Do not manually set a sibling task active while the current active/completed task has unfinished children, unless the user explicitly overrides the tree order.
- Do not invent task updates that were not actually completed.
- Do not overwrite a task body with a report, transcript, or progress log just
  because the task produced one; write those outputs under
  `task_tree/files/<task-id>/` and leave the body as the plan plus any needed
  concise resume pointer.
- Do not outsource the essential compaction handoff to `notes/` alone when it should live in the task body / active task.
- Do not use `/tmp` for task-owned artifacts when `task_tree/files/<task-id>/`
  is available.
- Do not silently delete a subtree; warn the user first if the task has children.
- Do not overwrite the backing file except through the script.
- Do not assume concurrent writers are harmless; use the script so locking is applied.

## Iteration Notes

This first Codex port favors transparency and durability over sophistication:

- JSON file storage instead of SQLite
- CLI script instead of Python `exec(...)`
- optional shared and per-task artifact folders
- filesystem locking plus atomic writes for shared-tree safety
- per-event timestamps for task lifecycle changes
- enough operations for daily use, with room to add richer reporting later
