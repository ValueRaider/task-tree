# Destructive Operations and Artifact Recovery

Use this reference before deleting task records or managed artifact
directories. These commands commit tree metadata before attempting filesystem
cleanup. They are crash-consistent and recoverable, not one transaction across
JSON and directories.

## Commands

```bash
# Inspect without changing anything; optionally prune canonical orphans.
python .agents/skills/task-tree/scripts/task_tree.py scan-files
python .agents/skills/task-tree/scripts/task_tree.py scan-files --prune --json

# Delete one record or forced subtree, then clean referenced managed paths.
python .agents/skills/task-tree/scripts/task_tree.py delete 3

# Detach and clean one task's managed directory.
python .agents/skills/task-tree/scripts/task_tree.py prune-files 3

# Clear metadata and canonical task directories.
python .agents/skills/task-tree/scripts/task_tree.py reset

# Select cleanup and whether the backing JSON remains.
python .agents/skills/task-tree/scripts/task_tree.py clear \
  --prune-files --prune-shared --drop-file
```

Use `<command> --help` before adding options such as `delete --force` or
changing clear/reset cleanup. The global `--tree-file PATH` option goes before
the subcommand.

## Safe inventory and ownership

`scan-files` classifies the selected store's task-artifact root while holding
a shared lock. With `--prune`, it holds the exclusive lock and removes only
orphaned immediate child directories whose names are canonical positive task
IDs. An absent tree supplies an empty live set, so scanning can recover
leftovers after `--drop-file`.

Symlinks, regular files, nonnumeric names, noncanonical stored `files_dir`
values, and missing referenced directories are suspicious. They are reported
but never recursively removed. `shared/`, the tree JSON, its lock, and
unrelated sibling paths are outside scanner scope.

JSON inventory output has stable `files_root`, `live`, `orphaned`,
`suspicious`, `removed`, and `failed` fields. A scan exits `1` only when
pruning records a failure; suspicious entries alone are an inspection result.

## Command-specific effects

- `delete <id>` removes the task, or a subtree allowed by `--force`, from
  metadata and then cleans canonical managed directories referenced by the
  removed records. Surviving `return_to_id` references still block deletion.
- `prune-files <id>` keeps the task, commits `files_dir: null` and
  `files_detached_at`, then attempts cleanup. When already detached, rerunning
  it retries the canonical path idempotently.
- `reset` commits an empty tree and always requests cleanup of canonical task
  directories.
- `clear` cleans task or shared artifacts only with `--prune-files` or
  `--prune-shared`; otherwise those artifacts intentionally remain. This includes
  the tree-wide notepad: pruning shared removes all notes for trees sharing that
  parent directory; ordinary reset/drop/clear preserves them.
- `--drop-file` durably removes the tree JSON instead of writing an empty
  tree. Unsafe shared roots and suspicious task-root entries are retained.

All these operations hold one exclusive store lock from validation through
cleanup. Metadata is durably committed or removed before recursive deletion,
so a crash cannot leave committed live metadata pointing to an artifact path
deleted by that operation. Recursive deletion is best effort, may be partial,
and is never rolled back after the metadata commit.

## Results, exits, and recovery

`delete`, `prune-files`, `clear`, and `reset` accept `--json`. Their structured
result includes `metadata_committed: true` and a `cleanup` object with
`requested`, `removed`, `absent`, `unmanaged`, and `failed` arrays.

- Exit `0`: requested managed cleanup completed or paths were already absent.
- Exit `1`: metadata committed, but an unmanaged or failed path remains.
- Exit `2`: usage, validation, collision, or another pre-commit rejection;
  cleanup did not begin.

After exit `1` or an interrupted cleanup, inspect retained paths with
`scan-files` and use `scan-files --prune` only for confirmed managed task
orphans. Retrying `delete` is not recovery because its task record is already
gone. `prune-files` is intentionally retryable after detachment.
