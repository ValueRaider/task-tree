# Atomic Task Partitioning

Use `partition` after a staged plan has been accepted and its ordered children
are ready to record together:

```bash
python .agents/skills/task-tree/scripts/task_tree.py partition <parent-id> \
  --from-file PATH [--set-active-first] [--full-tree]
```

Place the global `--tree-file PATH` option before `partition` when selecting a
non-default tree. `--set-active-first` activates only the first newly created
child. Mutations print the compact snapshot by default; `--full-tree` requests
the full post-mutation tree.

The input file has exactly this schema. Array order becomes child order:

```json
{
  "schema_version": 1,
  "steps": [
    {
      "summary": "Implement the first bounded stage",
      "body": "Describe the outcome, validation, and handoff."
    },
    {
      "summary": "Validate the integrated result",
      "body": "Review the scoped diff and run the broader checks."
    }
  ]
}
```

The top-level object may contain only `schema_version` and `steps`.
`schema_version` must be integer `1`, and `steps` must be a non-empty array.
Each step may contain only `summary` and `body`; both must be strings that are
non-empty after whitespace trimming. Valid surrounding whitespace is retained
in the stored strings.

The parent ID comes only from the CLI. IDs, statuses, prerequisites,
permissions, checkpoints, artifact fields, and other planning metadata are not
accepted in the file.

The command parses and validates the whole file before taking one exclusive
store lock. In that transaction it verifies the parent, allocates normal IDs
and lifecycle events, creates `not_started` children in array order, appends
them after existing direct children, invalidates the parent's
`closeout_reviewed` flag when necessary, and optionally activates the first
new child. It does not create artifact directories.

Invalid input or a missing parent exits before the canonical tree JSON is
written. Lock-file creation for an attempted locked operation is not a tree
mutation.
