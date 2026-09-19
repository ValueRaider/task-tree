# task-tree

A durable adaptive task-tree for keeping Codex work structured across long, multi-session projects. 
Switch workstreams, reorder priorities, and resume with durable context.

Self-contained skill - just copy `task_tree` into your skills folder.

## Why?

This is for projects that start with a plan, but that plan evolves massively as you progress.
- You need to switch to some priority work then return.
- Elaborate on part of project plan.
- Insert some prerequisite work.
- Reorder parts of project plan.

You want to do this without your current work being damaged by context compaction.

## What is a task

A task is a piece of work that is intended to fit within the 250k context window.
Basically it is a body of text with some files. It also has metadata like state and timestamps.
This is all persisted outside the context window in a local folder, so survives compaction.

## What is the tree?

If a task is expected to exceed the context window, then spread work over a set of *child* tasks.

```
$ python .agents/skills/task-tree/scripts/task_tree.py show
• [~] #1 Build and publish the first release
    [x] #2 Define scope and acceptance criteria
    [~] #3 Implement core workflow
      [x] #4 Create the project skeleton
      [~] #5 Add the primary command << ACTIVE
      [ ] #6 Validate error handling
    [ ] #7 Review the integrated release
      [ ] #10 Investigate an unexpected validation failure
      [ ] #11 Apply and verify the repair
    [ ] #8 Prepare documentation and publish
    [ ] #9 Investigate a future integration
```

As you work through your task-tree, you can adjust it:
- Add child tasks to an existing task.
- Reorder tasks.
- Delete a sub-tree.
