# Legacy migration example

This directory is a committed isolated task-tree fixture for designing and testing the
legacy-to-parent-owned-children schema migration. It does not modify the live
`task_tree/tree.json`.

The source file, `legacy-tree.json`, uses the current legacy representation:
each node persists `parent_id` and `sibling_order`.

Important fixture properties:

- Root order is `#2, #1`, deliberately different from ID order.
- Direct children of `#1` are `#3, #5, #4, #7, #9`, also different from ID order.
- `#4` is active and has pending child `#6`, so next-task selection must choose
  `#6` before returning to `#4`.
- `#7` has completed child `#8`, exercising nested terminal structure.
- The fixture includes completed and impossible states.
- Task `#4` owns `files/4/sample.txt`, exercising artifact-path preservation.

Behavioral baselines captured before migration:

- `expected-full-tree.txt`
- `expected-next.txt`
- `expected-path-to-6.txt`

Tests and migration experiments must work on a copy of `legacy-tree.json`, never
on the live task tree or on this preserved source fixture.
