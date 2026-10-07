# Ordering and Traversal

## Ordered ownership

Each parent's direct children are an ordered list stored once in its `children`
array. Top-level tasks use the same model through `root_ids`. A task record does
not persist its own `parent_id` or `sibling_order`; commands derive those values
for JSON views. The physical order of records in `nodes`, task IDs, and
timestamps do not control execution order.

New tasks and tasks moved under a different parent are appended after that
parent's existing children. `reorder` changes a task's position in its current
owning list. See [schema.md](schema.md) for the persisted ownership contract.

## Focus and traversal

The active task is an explicit pointer, not something inferred from sibling
order. Reordering siblings does not change which task is active.

Pending descendants of the active task take priority over the active task
itself. Otherwise an actionable active task retains focus, so merely inserting
a sibling before it does not pre-empt it. After a task becomes terminal,
traversal proceeds through later sibling branches, offers an actionable parent
for required closeout after its child work is terminal, and then climbs toward
the roots. Normal active traversal does not wrap from the final root to an
earlier root.

When a newly inserted task must run before the currently active middle child,
change both its sibling position and the active pointer.

## Insert before the active child

Assume parent `#10` has children `#11`, `#12`, and `#13`, with `#12` active.
To insert a new prerequisite before `#12`:

```bash
# Addition appends the task; assume its new ID is #20.
python .agents/skills/task-tree/scripts/task_tree.py add \
  "New prerequisite" --parent 10
python .agents/skills/task-tree/scripts/task_tree.py reorder 20 --before 12
python .agents/skills/task-tree/scripts/task_tree.py set-active 20
```

The resulting order is `#11`, `#20`, `#12`, `#13`, with `#20` active. Normal
forward traversal returns to `#12` after `#20` completes. If only future order
should change, omit `set-active`; the existing active task retains focus, so do
not describe the inserted task as an immediate prerequisite.

## Plain and explicitly relative `next`

`next` and `next <task-id>` answer different questions:

- Plain `next` follows active focus. It checks pending descendants before the
  active task itself. From a terminal active task it moves forward after that
  branch, offers an actionable parent for closeout when appropriate, and climbs
  toward the roots. With no active task, it returns the first pending task in
  depth-first tree order.
- `next <task-id>` is a non-mutating inspection relative to that task. After
  exhausting the task and its descendants, it searches later sibling branches,
  then earlier sibling branches, before an actionable parent. The same
  later-then-earlier search applies at the root.

The relative query's wraparound helps inspect work near an arbitrary historical
task. It is not the forward-only auto-advance policy used when active work
completes.

## Reordering

`reorder` accepts `--first`, `--last`, `--before <sibling-id>`,
`--after <sibling-id>`, or `--before-first-pending`. A `--before` or `--after`
anchor must have the same parent. Here, pending means `in_progress` or
`not_started`. `--before-first-pending` appends when no pending sibling exists.
Use native `reorder --help` for the complete accepted syntax.
