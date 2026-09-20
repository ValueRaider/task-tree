# Parent Closeout Review

Set a parent `in_progress` when starting that branch and work its children in
tree order. Children existing or becoming terminal does not itself complete the
parent. After the final direct child is terminal, re-read the parent’s summary
and body before leaving the branch. Decide whether its outputs satisfy the
closeout criteria, it has a real remaining action, its planning wording is
stale, or it is obsolete.

This review is automatic when an actionable parent has children and every
direct child is `completed`, `aborted`, or `impossible`; do not wait for the
user to ask. Do not continue from a parent’s old wording without checking if
its children already met the purpose.

Each task has `closeout_reviewed`, normally `false`. Set it to `true` only once
the direct children have been processed:

- If the parent is done, set a terminal status.
- If it remains actionable after review, set `closeout_reviewed: true` to avoid
  repeating the closeout-due warning. `next` may still return it as ordinary
  unfinished work.
- Adding, moving, deleting, or changing a child’s status invalidates the
  parent flag.

Therefore, after completing an active child with no pending siblings, the next
actionable task may be its parent. This is expected. If a parent really must be
deferred, make that true in the tree: do not leave it actionable, place it after
its gate, state the gate in its body, and make the actual next task active.
