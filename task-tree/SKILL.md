---
name: task-tree
description: Persist and inspect project task trees across sessions, compaction, restarts, and handoffs. Use for multi-session work or explicit `$task-tree` requests; not for short, single-turn todo lists.
---

# Task Tree

The recorded tree is the authoritative plan for this project. Do not replace it
with a remembered, conversational, or ad-hoc task list. On “proceed”,
“continue”, or similar, execute the next actionable tree task unless the user
explicitly overrides it.

Use `scripts/task_tree.py` for every read and write; it is the task-tree API.
If its CLI lacks an operation, inspect and extend it deliberately rather than
editing the JSON directly. Before using an unfamiliar mutation flag, consult
`task_tree.py --help`, `<command> --help`, or the argument parser—do not guess.

The default tree is `./task_tree/tree.json`. Put `--tree-file PATH` before the
command to select another tree. That selected file’s parent owns its `files/`,
`shared/`, and lock artifacts. The runtime uses a filesystem lock and durable
atomic replacement for the tree JSON; always use the script so concurrent
changes serialize safely. Artifact-directory cleanup is a separate,
crash-consistent step, not part of the atomic JSON replacement. It validates
the current parent-owned ordering schema before every operation; see
[schema.md](references/schema.md) when diagnosing a schema error.

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

Read [tui.md](references/tui.md) before using the optional interactive viewer;
it covers its dependency, navigation, relocation, and session-local undo.

Before choosing work, inspect the active task and/or run `next`. Keep one
actionable task active when there is a clear focus. Do not jump to a sibling
while the current active task, including a terminal one, has unfinished
children unless the user explicitly says to override tree order. Never manually
activate a terminal task; an automatic `return_to_id` continuation may
intentionally restore focus to one for review, reopening, or traversal.

### Tree-wide notepad

Before beginning work on a task, inspect its details and the tree-wide notepad.
The CLI includes the note automatically in snapshots and active-task detail
output (text and JSON); no separate notepad read is needed. Merely changing the
active task does not require another read. Use the notepad for cross-task
navigation facts, workflow preferences and caveats, not execution permissions,
task status, acceptance criteria or a second task list. Prefer storing cross-task
preferences in the notepad unless a clear alternative home is known. If such a
home exists, maintain the preference there rather than duplicating it; add a
notepad pointer when useful.
Keep essential task-specific constraints in task bodies. Maintain the note rather
than accumulating history; link detailed evidence and remove stale entries.

Use the `notepad show`, `notepad replace` and `notepad clear` CLI operations,
not direct writes to reserved storage. See
[the notepad contract](references/artifacts-and-events.md#tree-wide-notepad)
for limits, ownership, isolation and cleanup behavior.

## Creating and Placing Work

Tasks are small, concrete units with a summary and body. A parent is a real
task, not a heading: it states purpose, gates, closeout criteria, and handoff.
Any task may receive children; parent/child expresses relationship, not type.
Adding children does not make the parent complete or non-actionable.
The frontier comprises tasks without children; it does not determine their
status, readiness, or whether a parent has work of its own.

Before substantive execution, decide and record whether the objective is one
coherent task or a staged parent. Stage it before implementation or delegation
when it has multiple independently verifiable outcomes, delegation units,
distinct phases, failure mechanisms, or useful checkpoint boundaries;
otherwise keep one task. Use the
[partition command](references/partitioning.md) to create an accepted
staged plan atomically.

In a staged plan, the parent retains the overall acceptance criteria and each
child owns one useful, verifiable outcome with its validation and handoff. Put
dependencies in sibling order, set the parent `in_progress`, and activate the
first actionable child. Do not split work merely by file, test, command, or
routine message. Advance only after reviewing and validating the child and
taking any appropriate scoped checkpoint.

Read [task-sizing.md](references/task-sizing.md) when staged boundaries or
context fit are non-obvious, before assigning several delegated units, and
whenever scope expands or an unexpected dependency, failure mechanism, or
ownership boundary appears. Stop and repartition at such a boundary before
continuing; the reference defines the detailed sizing, checkpoint, and handoff
procedure.

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
insertion, placement, and traversal rules, read
[ordering-and-traversal.md](references/ordering-and-traversal.md).

### Temporary switches

Before creating or changing work that may temporarily interrupt the current
focus, read
[temporary-interruptions.md](references/temporary-interruptions.md). It owns
the temporary-versus-permanent decision, parentage, syntax, firing, and
validity rules.

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
[artifacts-and-events.md](references/artifacts-and-events.md).

Destructive commands commit the tree before attempting managed artifact
cleanup. If cleanup is interrupted or reports retained paths, use `scan-files`
to inspect them and `scan-files --prune` to remove only canonical orphan task
directories. The scanner reports but never automatically removes suspicious
entries; see
[destructive-operations.md](references/destructive-operations.md).

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

### Compact but readable handoffs

Task bodies must remain understandable across sessions and by different agents.
“Compact” means removing unnecessary content—not removing word boundaries or
requiring readers to reconstruct intent.

**Prefer:**
- Concise sentences and structured sections: scope, constraints, acceptance
  criteria, and handoff.
- Removing repetition and obsolete history.
- Linking detailed evidence while retaining essential instructions in the body.
- Established abbreviations and exact code identifiers.
- Short names for recurring concepts, with explicit definitions available
  wherever those names are used.

**Avoid:**
- Concatenating ordinary words, such as `immutablefullfacts`.
- Unexplained abbreviations or invented terms.
- Compressing several distinct obligations into an ambiguous phrase.
- Moving essential safety constraints or completion gates exclusively into
  linked artifacts.
- Assuming fewer characters means fewer tokens.

Before saving a task body, check:
1. Can another agent identify the required actions and completion conditions
   without reconstructing the author’s intent?
2. Are unfamiliar terms defined and references clearly identified?
3. Has shortening preserved ownership, permissions, uncertainty, and dependencies?

If not, expand or restructure the wording.

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

Only when the user or project instructions have already authorized Git commits
for the current workflow, prefer small durable scoped commits over an
accumulating working-tree diff. Repository presence and silence about commits
are not authorization. A task checkpoint and a Git checkpoint serve different
purposes. Never stage or commit unrelated dirty files.

Before multi-commit work, branch changes, or merging a task subtree, read
[git-backed-work.md](references/git-backed-work.md).

## Command Reference

Use these everyday operations. For complete accepted syntax and output
options, run `python .agents/skills/task-tree/scripts/task_tree.py --help` or
append `--help` to a subcommand; do not load a prose catalog for ordinary CLI
syntax.

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
`impossible` are terminal. Load the scenario references above only when their
extra semantics are needed.

## Design Notes

This implementation favors transparent, durable JSON storage, a CLI API,
explicit artifact folders, filesystem locking, and lifecycle timestamps over a
more sophisticated hidden system. One tree JSON replacement is atomic for
cooperating readers. A mutation that also removes directories is instead
tree-first, crash-consistent, and recoverable through orphan scanning; it is
not one cross-resource atomic transaction.
