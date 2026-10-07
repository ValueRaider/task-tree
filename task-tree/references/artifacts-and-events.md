# Task Artifacts and Progress Events

Use task artifacts for detailed outputs and the append-only event log for
short factual progress or resume pointers. With the default store, shared
artifacts live in `task_tree/shared/`, per-task artifacts in
`task_tree/files/<task-id>/`, and events in that task directory's
`events.jsonl`. For `--tree-file PATH`, the selected file's parent owns the
corresponding `shared/` and `files/` directories.

## Create and inspect task data

```bash
python .agents/skills/task-tree/scripts/task_tree.py ensure-files 2
python .agents/skills/task-tree/scripts/task_tree.py shared-dir

python .agents/skills/task-tree/scripts/task_tree.py log-event 2 \
  --event repair_completed \
  --summary "Fixed section binding regression" \
  --evidence task_tree/files/2/repair.log \
  --next-action "Re-run focused validation"

python .agents/skills/task-tree/scripts/task_tree.py checkpoint 2 \
  --summary "Prepared resume handoff after focused validation" \
  --next-action "Inspect the regenerated output set" \
  --body-file task_tree/files/2/resume_body.txt

python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --tail 10
python .agents/skills/task-tree/scripts/task_tree.py event-log 2 --json --tail 20
```

`add --with-files`, `ensure-files`, `log-event`, and `checkpoint` create or
attach the canonical task directory when needed. `checkpoint` updates its
optional replacement body inside the locked tree transaction and appends the
event while that store lock is held. The JSONL append and tree replacement are
separate filesystem writes, not one cross-resource atomic commit. Event
evidence and changed-file fields may be repeated; consult each subcommand's
`--help` for the complete record fields.

## Attachment and collision rules

Artifact creation never adopts a pre-existing canonical
`files/<task-id>` path for a node whose `files_dir` is null. Creation fails
with a collision diagnostic so recovery data is not silently reused. Inspect
the path and prune it only after confirming that it is an orphan. A task
already attached to its canonical path may keep using it.

Canonical relative and absolute `files_dir` spellings are accepted. An edited
path outside the selected store's exact `files/<task-id>` ownership boundary
is not managed by task-tree.

## Lifecycle timestamps versus progress events

Task lifecycle timestamps include `created_at`, `activated_at`,
`status_changed_at`, `summary_updated_at`, `body_updated_at`, `moved_at`,
`files_created_at`, `files_detached_at`, and `last_mutated_at`; inspect them
with `show <id> --details`. They are record metadata, distinct from the
append-only progress-event log.

`files_detached_at` records the metadata commit that cleared `files_dir`; it
does not assert that physical directory cleanup completed.
