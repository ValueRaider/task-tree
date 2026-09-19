# Execution Order and Insertion

## Ordered children

Each parent's direct children behave as an ordered list. The backing JSON does
stores that list once, in the parent's `children` array. Top-level tasks use the
same model through the tree's `root_ids` array. A task record does not persist
its own `parent_id` or `sibling_order`; commands derive those values when a JSON
view needs them. The physical order of records in `nodes`, task IDs, and
timestamps do not control execution order.

New tasks and tasks moved under a different parent are appended after that
parent's existing children. The `reorder` command changes the ID's position in
its existing owning list. See [schema.md](schema.md) for the complete persisted
ownership contract.

## How the active task affects traversal

The active task is an explicit pointer, not something inferred from sibling
order. Reordering siblings does not change which task is active.

While the active task remains actionable, it retains focus; merely inserting a
new sibling before it does not pre-empt it. Pending descendants of the active
task take priority over the active task itself. Once a task is terminal,
traversal normally continues forward through later siblings and their
descendants, then climbs to the parent for any required closeout.

Therefore, when a newly inserted task must run *before* the currently active
middle child, both its position and the active pointer must be changed.

## Insert a new child before the active child

Assume parent `#10` has ordered children `#11`, `#12`, and `#13`, with `#12`
active. To insert a new prerequisite before `#12`:

```bash
# Addition appends the task and prints its new ID; assume it is #20.
python .agents/skills/task-tree/scripts/task_tree.py add \
  "New prerequisite" --parent 10

# Put the new task immediately before the formerly active sibling.
python .agents/skills/task-tree/scripts/task_tree.py reorder 20 --before 12

# Transfer focus so the insertion really executes before #12.
python .agents/skills/task-tree/scripts/task_tree.py set-active 20
```

The resulting sibling order is `#11`, `#20`, `#12`, `#13`, and `#20` is
active. When `#20` completes, normal forward traversal returns to `#12`.

If the intent is only to change the future display/traversal order without
interrupting current work, omit `set-active`. In that case, the existing active
task remains active; do not describe the new task as an immediate prerequisite.

## Normal versus explicitly relative `next`

`next` and `next <task-id>` answer different questions:

- Plain `next` follows the active focus. It checks pending descendants before
  the active task itself. When calculating from a task that has just become
  terminal, it proceeds forward after that branch, offers an actionable parent
  for closeout when appropriate, and climbs toward the roots. It does not wrap
  from the last root back to earlier roots. With no active task, it returns the
  first pending task in depth-first tree order.
- `next <task-id>` is an inspection query relative to the supplied task and
  does not change active focus. After exhausting that task and its descendants,
  it checks later sibling branches, then earlier sibling branches, before an
  actionable parent; the same later-then-earlier search applies at the root.

The wraparound in the explicitly relative query helps inspect what remains near
an arbitrary historical task. It is not the forward-only auto-advance policy
used when a currently active task completes.

## Other reorder operations

```bash
python .agents/skills/task-tree/scripts/task_tree.py reorder <id> --first
python .agents/skills/task-tree/scripts/task_tree.py reorder <id> --last
python .agents/skills/task-tree/scripts/task_tree.py reorder <id> --before <sibling-id>
python .agents/skills/task-tree/scripts/task_tree.py reorder <id> --after <sibling-id>
python .agents/skills/task-tree/scripts/task_tree.py reorder <id> --before-first-pending
```

The target of `--before` or `--after` must have the same parent. Here,
"pending" means `in_progress` or `not_started`.

## Temporary priority work and `return_to`

Hierarchy and sibling order should continue to express the project plan. When
an urgent task temporarily interrupts another branch, use a return continuation
instead of distorting that plan merely to recover the earlier focus:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add \
  "Investigate urgent regression" --return-to 654 --set-active
```

The stored field is `return_to_id`; the CLI spells it `--return-to ID`. The
continuation fires only when all of the following are true:

1. the task being completed is the current focus;
2. its status crosses from actionable to terminal; and
3. the task carrying the nearest return continuation, which may be an ancestor
   of that completed task, is terminal with no actionable descendants.

At that point the referenced task becomes the focus before ordinary sibling or
parent traversal is considered. The target may itself be terminal: the return
is a request to restore a location in the plan, not an assertion that the
target is new work. A later `next` calculation traverses normally from that
focus, while the user may instead review or reopen it.

The transition triggers the continuation once. Merely encountering the same
terminal task later does not re-fire its stored edge. A missing target is
invalid; deletion therefore refuses to remove a task still referenced by a
surviving `return_to_id`. Clear or replace those references first.

A task cannot return to itself or into its own subtree. Its descendants must
already be finished before the continuation can fire, so such an edge would
only refocus completed subordinate work and obscure the intended control flow.
