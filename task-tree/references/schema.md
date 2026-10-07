# Persisted Task-Tree Schema

## Canonical store and selection

The ordinary shared store is `task_tree/tree.json`. The `--tree-file PATH`
global command-line option selects an explicit store for one invocation. Schema
versions never appear in these filenames, and the runtime does not probe
alternative filenames to find a tree with a different format. The selected JSON
file's parent directory owns the corresponding `files/`, `shared/`, and lock
artifacts.

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

`events` is a lifecycle-timestamp object. Artifact attachment records
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

Reads validate these invariants before commands operate on the tree, and every
write validates them again before atomic replacement. `clear-active` is the one
recovery exception: its read may skip only active-pointer validation, then it
sets the pointer to null and performs full validation before writing. It cannot
rewrite a structurally invalid graph.

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
