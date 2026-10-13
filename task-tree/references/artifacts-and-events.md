# Task Artifacts and Progress Events

Use task artifacts for detailed outputs and the append-only event log for
short factual progress or resume pointers. With the default store, shared
artifacts live in `task_tree/shared/`, per-task artifacts in
`task_tree/files/<task-id>/`, and events in that task directory's
`events.jsonl`. With `--tree-dir PATH`, that directory owns the corresponding
`tree.json`, `shared/` and `files/` paths.

## Compact, readable handoffs

Task bodies must remain understandable across sessions and by different agents.
“Compact” means removing unnecessary content—not removing word boundaries or
requiring readers to reconstruct intent.

Prefer concise sentences and structured sections for scope, constraints,
acceptance criteria, and handoff; remove repetition and obsolete history; link
detailed evidence while retaining essential instructions in the body; and use
established abbreviations and exact code identifiers. Define short names for
recurring concepts wherever they are used.

Avoid concatenating ordinary words, unexplained abbreviations or invented
terms, compressing distinct obligations into ambiguous phrases, moving
essential safety constraints or completion gates exclusively into linked
artifacts, or assuming fewer characters always means fewer tokens.

Before saving, check that another agent can identify required actions and
completion conditions without reconstructing intent, unfamiliar terms and
references are clear, and shortening preserves ownership, permissions,
uncertainty, and dependencies. If not, expand or restructure the handoff.

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
separate filesystem writes, not one cross-resource atomic commit. An event is
not proof that a checkpoint body change committed. If an attached event log is
unreadable or malformed, task views that display log evidence show an explicit
warning while retaining valid task data; unrelated task mutations must not depend on reading
that ancillary log. A direct event-log request may fail with the diagnostic.
Do not truncate, repair, retry or discard the log automatically. Event
evidence and changed-file fields may be repeated; consult each subcommand's
`--help` for the complete record fields.

## Attachment and collision rules

Ordinary artifact creation never adopts a pre-existing canonical
`files/<task-id>` path for a node whose `files_dir` is null. Creation fails
with a collision diagnostic so recovery data is not silently reused. Inspect
the path before deciding what it belongs to. Once the user/owner has
confirmed that this exact directory belongs to the task, `ensure-files <id>
--attach-existing` explicitly attaches its existing canonical directory without
changing its contents. This flag never guesses association and still rejects a
non-directory or noncanonical target. It is harmless when already attached;
when the directory is absent, normal creation applies. Event evidence is read
only from an attached directory, never from a fallback path for an unattached ID.

If association is unknown or belongs to old work, preserve the exact folder by
an explicitly approved filesystem move to an operator-selected location before
creating a new task folder. Record that location. Do not prescribe bulk
`scan-files --prune` to resolve one collision or infer disposability from a
scanner label. This is artifact recovery, not permission to edit tree JSON. A task
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

Each operation supports `--json`; put `--tree-dir PATH` before `notepad` to
select another tree. Replacement is complete, not an append. The code enforces
at most **200 whitespace-separated words and 8192 UTF-8 text bytes**, including
bounded file reads. Oversized input is refused without replacing the note.
Empty text is permitted; `clear` removes it. No automatic truncation.

### Reserved storage and ownership

The store directory reserves `shared/.task-tree-notepad.md`. A managed header
identifies the note as task-tree content, not filesystem access control.
Legacy filename-bound notes are handled only by the directory canonicalization
procedure in [schema.md](schema.md). Ordinary artifacts must not use reserved
`.task-tree-notepad` names. No generic `shared/notepad.md` is adopted.

Use ordinary filesystem operations. Accept readable regular UTF-8 text with
the managed header and documented size bounds; report actual I/O errors.
Refuse unexpected file types rather than blocking on devices or pipes.

Writers and readers use the directory store lock. Replacement writes a temporary
file and atomically replaces the note; flush and synchronize as for persisted
state. A failure after replacement can leave new content visible: inspect the
state rather than automatically retrying. Note operations do not rewrite tree
JSON or unrelated artifacts. The selected store directory is the boundary for related task data.

### Lifetime

Task completion, deletion, switching, reset and ordinary clear do not remove
the notepad. As with other shared artifacts, explicit `clear/reset --prune-shared`
removes the **entire shared directory**, including the selected store's notepad and 
any retained legacy note. This broad cleanup requires explicit authorization; 
it is not the response to an ordinary note or attachment error. Dropping the
tree JSON without pruning shared artifacts preserves its note. `scan-files`
does not manage shared notes. These operations still require their existing
permissions; a note does not grant disposal authority.
