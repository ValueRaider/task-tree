# Temporary Interruptions and Return Continuations

Use a return continuation when work in another branch temporarily interrupts
the current focus and that focus should be restored afterward. Do not set one
for an explicit permanent reprioritization. If the request does not establish
whether the switch is temporary, ask whether the user wants to resume the
current task afterward.

Hierarchy and sibling order continue to express the project plan. Parentage and
return continuation are independent, so urgent work may belong under another
workstream while returning to the interrupted task after the urgent subtree is
terminal.

## Create or change an interruption

Create and activate temporary work with the interrupted task as its target:

```bash
python .agents/skills/task-tree/scripts/task_tree.py add \
  "Investigate urgent regression" --return-to 654 --set-active
```

The CLI spells the option `--return-to ID`; the stored field is `return_to_id`.
Use `update <id> --return-to ID` to replace a continuation and
`update <id> --clear-return-to` to remove one.

## When a continuation fires

The nearest continuation carried by the completed task or one of its ancestors
fires only when all of these conditions hold:

1. the task being completed is the current focus;
2. its status crosses from actionable to terminal; and
3. the continuation-bearing task is terminal with no actionable descendants.

The referenced task receives focus before ordinary sibling or parent traversal.
It may itself be terminal: a return restores a location in the plan rather than
asserting that the target is new work. Direct `set-active` still rejects a
terminal task. A later `next` traverses normally from the restored focus, while
the user may instead review or reopen it.

The continuation fires once for that actionable-to-terminal transition.
Merely encountering the same terminal task later does not fire it again.

## Valid references

The target must exist. A task cannot return to itself or to a descendant in its
own subtree; that subtree must already be finished before the continuation can
fire. Deletion refuses to remove a target referenced by any surviving
`return_to_id`; clear or replace those references first. Deleting a subtree that
contains both the source and target does not leave an invalid reference.

See [schema.md](schema.md) for the complete persisted reference invariants.
