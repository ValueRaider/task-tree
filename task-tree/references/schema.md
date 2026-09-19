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

If an existing **populated** tree lacks `schema_version` but has an unambiguous
current relationship shape—top-level `root_ids`, `children` on every node, and
no legacy relationship fields—the runtime initializes and persists
`schema_version: 2`. It validates the complete tree before that metadata-only
write. Empty, legacy, mixed, ambiguous, or otherwise invalid input is never
inferred or rewritten by this rule.

## Legacy recognition

The old format stored `parent_id` and `sibling_order` on each task and had no
parent-owned `children` or top-level `root_ids`. The runtime recognizes a
consistent old shape so it can give a manual-migration diagnostic, but it never
converts, fills, or rewrites that input. Mixed, partial, conflicting, and
unknown-version structures are rejected rather than guessed from task IDs.

For the explicit conversion procedure, see [migration.md](migration.md).
