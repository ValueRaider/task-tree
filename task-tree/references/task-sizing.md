# Sizing and Repartitioning Complex Work

Use this reference when the `SKILL.md` hot path routes here: staged boundaries
or context fit are non-obvious, several delegated units are planned, or scope
changes reveal a new dependency, failure mechanism, or ownership boundary.

## Choose a context-fit boundary

Size the work to be attempted before the next durable stopping point, not the
whole objective represented by a parent. Consider the context needed to
understand the inputs, do the work, verify it, and record the handoff. Allow
room for uncertainty and findings that require revisiting earlier material;
file or line count alone is not a reliable workload estimate.

Identify a concrete stopping point and the evidence or artifact to preserve
there. If reaching it comfortably within the available context is doubtful,
add ordered children directly under the task before execution. Keep the
overall purpose and acceptance criteria on the parent; put each child's scoped
outcome, validation, and resume information on that child. Existing children
do not prevent adding further children where needed.

Choose boundaries that reduce how much context must be held at once and leave
a usable result for the next task. An independently checkable output can be a
useful boundary, but there is no required software-stage template.

## Preserve delegation boundaries

When several independent delegated-worker assignments are planned, give each
assignment its own ordered child. Task-tree and worker APIs do not enforce
structured `allowed_actions` or `forbidden_actions` permissions. Keep those
cross-role boundaries in the task body and worker assignment, with the owning
agent responsible for reviewing the result.

## Repartition when assumptions change

When scope expands or an unexpected dependency, failure mechanism, or
ownership boundary appears, stop at that boundary. Preserve the evidence and
completed work, then make the new ordered work and actual next action explicit
before continuing.

Reassess in the same way when unexpected investigation, repeated rereading, or
validation consumes the room reserved for finishing. Split the remaining work
before that room is exhausted; do not force an oversized task to completion
merely because its handoff could survive compaction.

Use task artifacts for detailed findings and the task body for the compact
plan and resume state, following the skill's handoff rules. A parent may span
many context windows; each individual work portion and its closeout still need
a context-fit boundary.
