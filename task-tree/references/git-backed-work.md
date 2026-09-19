# Git-Backed Task Work

Use Git to preserve coherent work without confusing a durable checkpoint with
task completion. These rules apply only when the project is a usable Git
repository and neither the user nor project instructions prohibit commits.

## Choose the Boundary

For a single coherent change, a scoped commit on the current branch may be
sufficient. For a substantive task-tree subtree whose intermediate commits are
useful for implementation, review, or repair but need not remain in the target
branch's history, prefer a short-lived branch for that coherent subtree.

Do not create a branch for every small task. The branch should correspond to a
parent objective with a meaningful integration gate. Record its name and base
commit in that parent's active task body or resume handoff so another session
can recover the exact Git context.

Do not rewrite existing target-branch history merely to retrofit work that
began before this workflow was chosen.

## Shared Working-Tree Ownership

In a shared working tree, branch and index state are global. One controlling
agent owns Git mutations for the subtree. Other agents and delegated workers
may inspect Git state but must not create, switch, merge, reset, rebase,
cherry-pick, stash, delete branches, stage files, or commit.

The controlling agent must not switch branches while another agent is actively
writing in the shared working tree. Inspect the status first and preserve all
unrelated or other-task changes.

## Checkpoint Commits

When a child task produces coherent, validated file changes, commit only its
owned paths before advancing. Inspect the staged diff and record the commit
hash and focused validation result in the child task's event log or completion
artifact.

If work pauses before completion, make a checkpoint commit only when the state
is internally coherent and its focused validation result is known. A
deliberately failing regression test may be a useful evidence checkpoint when
the failure is the stated outcome; label it clearly and record the unresolved
gate. Do not manufacture a commit from incoherent or unreviewed work merely to
empty the working tree.

Neither a checkpoint nor a passing focused test completes the parent. Keep the
task status aligned with its actual acceptance gates.

## Integrate the Subtree

Before merging, review the parent task and run its integration validation from
the completed branch state. Do not merge a branch with unresolved failures,
unfinished children, unrelated changes, or an unreviewed delegated diff.

When the intermediate commits have no lasting semantic value, prefer a squash
merge into the target branch so the target history records the coherent parent
outcome rather than every implementation attempt. Review the squashed diff and
validate the integrated result before completing the parent.

Record the final target-branch commit in the parent task's event log or
completion artifact. Delete the short-lived branch only after the merge and
final validation have been accepted.
