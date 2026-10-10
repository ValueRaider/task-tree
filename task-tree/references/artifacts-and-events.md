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

## Tree-wide notepad

The notepad is bounded shared context displayed in every compact text/JSON
snapshot and beneath task details in the TUI. CLI detail output for the active
task also includes it automatically: `show <active-id> --details` / `--json`,
`active` / `active --json`, detailed mutation output and `next` when it prints
the active task. Other commands using the same detail renderers include it
when their full detail output contains the active task. Text details append a labelled note;
JSON task records add a `notepad` field. Snapshots retain their single top-level
note, without duplicating it inside the active record. Inactive task details
and title-only or compact summary views do not acquire notes.

Prefer the notepad for cross-task preferences unless a clear alternative home
is known. Keep the preference in that home rather than duplicating it, with a
notepad pointer when useful. Navigation facts and caveats also belong here.
This context is not persisted task metadata, a second plan, execution permission
or an acceptance gate; task-specific permissions and safety constraints remain
in their owning tasks. Missing notes are explicit; invalid or unreadable notes
are shown as unavailable without hiding valid task data.

```bash
python .agents/skills/task-tree/scripts/task_tree.py notepad show
python .agents/skills/task-tree/scripts/task_tree.py notepad replace \
  --text "Source lookup: task_tree/files/635/relocation-map.md"
python .agents/skills/task-tree/scripts/task_tree.py notepad replace \
  --from-file path/to/replacement.txt
python .agents/skills/task-tree/scripts/task_tree.py notepad clear
```

Each operation supports `--json`; put `--tree-file PATH` before `notepad` to
select another tree. Replacement is complete, not an append. The code enforces
at most **200 whitespace-separated words and 8192 UTF-8 text bytes**, including
bounded file reads. Oversized input is refused without replacing the note.
Empty text is permitted; `clear` removes it. No automatic truncation.

### Reserved storage and ownership

The default tree reserves `shared/.task-tree-notepad.md`. Other tree filenames
use `.task-tree-notepad-<SHA-256 of tree filename>.md` in their parent's shared
directory, so different trees in the same directory have separate notes. The
folder stays flat. `.task-tree-notepad`-prefixed filenames are reserved for the
notepad facility; do not use them for ordinary artifacts. No generic
`shared/notepad.md` is read or adopted.

The storage API computes the canonical path and checks an exact managed header
bound to the tree filename, current-user ownership, mode 0600, one hard link,
regular-file type, UTF-8 and size limits. Unsafe paths, foreign/absent headers
and malformed files are refused on read/replace/clear, not adopted or deleted.
A copied file for another tree is a collision. Moving the entire tree directory
keeps the filename binding valid; renaming the tree file selects a different
note. Inspect a collision before requesting any manual cleanup.

CLI writers share the tree's exclusive lock; readers use the shared lock.
Replacement uses a private temporary file and atomic replacement. An error
after replacement/during directory sync can mean the new note is already
visible; inspect before deciding whether to retry. Note operations do not
commit task JSON or modify unrelated shared artifacts. There is no schema change.
This is executable validation of API-owned storage, **not filesystem access
control** against arbitrary external writes or forged headers. `shared-dir`
exposes the directory; it is not a generic artifact-file writer.

### Lifetime

Task completion, deletion, switching, reset and ordinary clear do not remove
the notepad. As with other shared artifacts, explicit `clear/reset --prune-shared`
removes the **entire shared directory**, including every note for trees sharing
that parent. This existing broad-cleanup behavior is unchanged. Dropping the
tree JSON without pruning shared artifacts preserves its note. `scan-files`
does not manage shared notes. These operations still require their existing
permissions; a note does not grant disposal authority.
