# Persisted Task-Tree Schema

## Canonical store and selection

The ordinary store directory is `task_tree/`. Select another directory with
`--tree-dir PATH` before the command. The directory owns `tree.json`,
`tree.json.lock`, `files/` and `shared/`; do not create a tree-name subdirectory.
Independent trees use independent directories chosen by the caller.

Selection is directory-based for every command and legacy selection route.
Inspect immediate JSON files only, not JSON artifacts inside files/ or shared/:

- No JSON file: use `tree.json`; normal write commands create it. Read commands
  may report an empty tree without creating its JSON.
- Exactly one JSON file already named `tree.json`: use it.
- Exactly one JSON file with another name: rename it to `tree.json` before the
  requested operation, preserving its bytes. Renaming is user-authorized even
  for a read invocation; report the old and new paths on stderr.
- Multiple JSON files: error listing the conflicting paths. Do not choose,
  overwrite, rename or prune anything. This includes destructive commands.

`--tree-file PATH` is strictly deprecated: convert its filepath to the parent
folder, then apply those same rules. Warn on stderr and recommend the concrete
`--tree-dir` replacement. The old basename is not a second selection rule.
`--tree-dir` and `--tree-file` are mutually exclusive. Explicit CLI selection
wins over the legacy TASK_TREE_FILE/TASK_TREE_AGENT environment selectors;
legacy selectors also reduce to their parent directory and warn to use
`--tree-dir`. Do not create named subfolders or permit an environment bypass.

All cooperating current commands acquire the directory's canonical
`tree.json.lock` before checking/renaming the JSON or touching artifacts.
Read-time canonicalization takes an exclusive lock for the rename; the normal
shared-read behavior can resume afterward. The multiple-file check also applies
when reset/clear skips parsing invalid tree contents. Cutover assumes old
program versions are not running concurrently; it does not synchronize arbitrary
external filesystem changes or old filename-specific locks.

Existing task artifact paths remain in the same parent directory. A legacy
notepad for JSON basename NAME is exactly
`shared/.task-tree-notepad-<SHA-256 of filesystem-encoded NAME>.md`; the default
`tree.json` instead uses `shared/.task-tree-notepad.md`. The legacy note begins
with `<!-- task-tree managed notepad: "NAME" -->` and a newline, with NAME encoded
as a JSON string (including its normal escaping). Only this exact managed path
and header identify the legacy note; do not search arbitrary Markdown files.

When renaming an existing noncanonical tree with such a legacy notepad, preserve
that note's text at the canonical tree's note path before renaming the JSON.
The canonical note uses the managed header for `tree.json`; compare note text
without the header. Refuse conflicting canonical/legacy note texts without overwriting either;
matching text is not a conflict. Keep the legacy note as retained recovery
material rather than deleting it. These are two filesystem changes, not an
atomic cross-file transaction: a failed preparation leaves the original tree
and note, possibly with an identical canonical note copy. A later invocation
can inspect that state; never claim an error proves no rename occurred. Report
native I/O errors and actual paths; no automatic retry, rollback or journal.

This is a bounded deprecation for existing callers/data explicitly approved by
the user, not a multi-tree store inside one directory. Each selected directory
owns one canonical tree and its associated `files/` and `shared/` data; use a
separate selected directory for each independent tree. Existing evidence is
read only from an explicitly attached canonical task directory; recovery
attachment rules are in [artifacts-and-events.md](artifacts-and-events.md#attachment-and-collision-rules).
No schema-version increment or broad data migration is introduced.

## Current stored shape

```json
{
  "schema_version": 2,
  "next_id": 10,
  "active_id": 4,
  "root_ids": [2, 1],
  "nodes": [
    {
      "id": 1,
      "children": [3, 5, 4, 7, 9],
      "summary": "Primary root",
      "body": "...",
      "status": "in_progress",
      "return_to_id": 8,
      "closeout_reviewed": false,
      "files_dir": null,
      "events": {}
    }
  ]
}
```

`nodes` is a flat record collection whose physical JSON order has no semantic
meaning. `root_ids` is the sole owner of root membership and order. Each node's
`children` list is the sole owner of its direct-child membership and order.
Nodes do not persist `parent_id` or `sibling_order`; the CLI may derive them for
display or JSON command output.

`active_id` is a separate focus pointer. Reordering a task does not implicitly
activate it. It is either null or identifies an existing task. Direct
`set-active` operations accept only `not_started` or `in_progress` tasks, but a
`return_to_id` continuation may focus a terminal task deliberately.

`return_to_id` is optional. When present, it is an execution-control reference,
not a hierarchy or ordering field. It identifies the task that receives focus
after this task becomes terminal and its subtree has no actionable work. It may
refer to an ancestor or another branch, including a terminal task, but not the
same task or one of its descendants.

`files_dir` is either null or a string naming the task's artifact directory.
The schema validates its type; filesystem ownership is a stricter CLI safety
policy. Automatic creation and recursive cleanup accept only the selected
store's canonical `files/<task-id>` path, allowing equivalent relative or
absolute spellings. Noncanonical edited values can be logically detached or
deleted with their task record, but task-tree reports and retains the named
filesystem path. A null `files_dir` does not prove the canonical path is absent:
an interrupted cleanup may leave an orphan for `scan-files` to report.

`events` holds lifecycle metadata, mostly timestamps, plus the opaque
`move_marker` used by the [TUI undo guard](tui.md#relocate-a-task). The marker
identifies a relocation; it is not a timestamp. Artifact attachment records
`files_created_at`; logical detachment records `files_detached_at` at the tree
commit and deliberately makes no claim that later directory cleanup succeeded.

## Required invariants

1. `schema_version` is exactly `2`.
2. Node IDs are unique positive integers, and `next_id` is greater than every
   stored node ID.
3. Every ID in `root_ids` and every `children` list resolves to one node.
4. Every node appears in exactly one owning position across those lists.
5. The graph is acyclic and every node is reachable from `root_ids`.
6. Every node has the required task payload fields and a valid status:
   `not_started`, `in_progress`, `completed`, `aborted`, or `impossible`.
7. `active_id`, when present, resolves to an existing task. CLI policy normally
   focuses actionable tasks; return continuations are the deliberate exception.
8. Every stored `return_to_id` resolves to an existing task and does not point
   to its own task or a descendant.

Ordinary reads validate these invariants before commands operate on the tree,
and every tree write validates them before atomic replacement. `clear-active`
may skip only active-pointer validation on read, then sets that pointer to null
and performs full validation before writing; it cannot repair an invalid graph.
Destructive `clear` and `reset` instead skip parsing the existing tree and
replace it with a validated empty tree, or remove it with `--drop-file`.
All these operations still apply the directory-selection and multiple-JSON
checks above. Artifact cleanup follows the
[destructive-operation contract](destructive-operations.md).

Tree writes flush the temporary JSON, atomically replace the selected file,
and synchronize its parent directory while holding the store lock. Removing
the tree with `--drop-file` also synchronizes the parent directory. That commit
does not include artifact directories. Destructive commands commit tree
metadata first, retain the exclusive lock through best-effort directory
cleanup, and may leave only unreferenced residue for later orphan pruning.

If an existing **populated** tree lacks `schema_version` but has an unambiguous
current relationship shape—top-level `root_ids`, `children` on every node, and
no unsupported child-owned relationship fields—the runtime initializes and
persists `schema_version: 2`. It validates the complete tree before that
metadata-only write. Empty, mixed, ambiguous, or otherwise invalid input is
never inferred or rewritten by this rule.

Unsupported child-owned relationship fields, partial structures, conflicting
ownership, and unknown schema versions are rejected rather than guessed from
task IDs.
