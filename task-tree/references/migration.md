# Manual Legacy-Tree Migration

The runtime does not auto-migrate. When it reports an old task-tree format,
stop ordinary task-tree commands and convert the intended file explicitly.

The current manual utility is:

```bash
python .agents/skills/task-tree/experiments/v2/migrate_v1_to_v2.py \
  task_tree/tree.json --in-place
```

In-place migration creates `task_tree/tree.json.v1.bak` before atomically
replacing the source. It refuses to overwrite an existing backup. Resolve that
backup deliberately instead of deleting it as an automatic retry step.

To inspect a converted copy before replacement:

```bash
python .agents/skills/task-tree/experiments/v2/migrate_v1_to_v2.py \
  task_tree/tree.json --output /tmp/task-tree-current.json
```

The utility validates legacy parent/order relationships before conversion and
validates the resulting current tree through the same schema module used by the
runtime. Migration maps legacy sibling order into parent-owned `children` and
`root_ids`, removes persisted `parent_id` / `sibling_order`, and preserves task
payloads and active focus. Ordinary current-schema runtime tests do not use the
migrator as a fixture factory.
