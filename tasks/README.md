# tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, the `plan()` handoff, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `annotate_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `plan()` tool with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff, and `/show-plan` to view the current plan (the `plan()` tool is hard-blocked in copilot sessions)
- **Workflow skills**: `gather`, `planning` SKILL.md content (the `agents` skill lives in the swarm context)

> **Note**: The workstream domain (`launch_workstream`, `list_workstreams`, `set_workstream_status`, and the `pi --workstream` startup flag) is owned by the swarm context (`swarm/ts/workstreams/`), persisted in the daemon's SQLite store. The agent tools (`dispatch_agent`/`wait_for_agent`/`list_agents`) are likewise swarm's.

## Functional smoke cleanup

For manual workstream smoke tests, use an obviously disposable label such as `functional-known-handle-smoke` and verify only the behavior under test: staging, `pi --workstream` agent attachment, known-handle `message_agent`, and known-handle `ask_agent` when the session is forkable.

Cleanup is manual by design:

1. Close the Herdr pane opened for the smoke workstream.
2. Remove the smoke worktree and branch using the normal reviewed git/worktree workflow for this repo.
3. If the smoke workstream record is clearly identified, remove it from the daemon's SQLite store or close it with `set_workstream_status`.

Do not add cleanup automation casually. Worktree deletion, branch deletion, and workstream-record mutation are destructive enough to need separate design.

## Dependencies

- **core** (`#core/*`): agent-mode, session state, workspace state + worktree operations, skill-tracker, catalog, model-aliases

## Type contracts

`TasksAccess`, `TaskStatus`, `Task`, `ReviewState`, `GoalCycle` are owned by this context (`tasks/ts/tasks/access.ts`) and exported through `#tasks/index.ts`. The tasks module implements `TasksAccess` and registers it at load; companion observes via `getTasksAccess()` (returns null until tasks registers it).
