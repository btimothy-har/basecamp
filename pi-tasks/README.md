# pi-tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, the `plan()` handoff, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `annotate_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `plan()` tool with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff, and `/show-plan` to view the current plan (the `plan()` tool is hard-blocked in copilot sessions)
- **Workflow skills**: `gather`, `planning` SKILL.md content (`agents` skill moved to pi-swarm)

> **Note**: The workstream domain (`launch_workstream`, `list_workstreams`, `set_workstream_status`, and the `pi --workstream` startup flag) has moved to `pi-swarm/extension` (in `src/workstreams/`). Workstreams are now persisted in the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams` and `workstream_agents`), replacing the former JSON launch-index. pi-tasks no longer owns this domain.

The sync in-process agent tool has been removed in the cutover. pi-swarm/extension now provides the sole agent tool (daemon-backed `dispatch_agent`/`wait_for_agent`/`list_agents`).

## Functional smoke cleanup

For manual workstream smoke tests, use an obviously disposable label such as `functional-known-handle-smoke` and verify only the behavior under test: staging, `pi --workstream` agent attachment, known-handle `message_agent`, and known-handle `ask_agent` when the session is forkable.

Cleanup is manual by design:

1. Close the Herdr pane opened for the smoke workstream.
2. Remove the smoke worktree and branch using the normal reviewed git/worktree workflow for this repo.
3. If the smoke workstream record is clearly identified, remove it from the daemon's SQLite store or close it with `set_workstream_status`.

Do not add cleanup automation casually. Worktree deletion, branch deletion, and workstream-record mutation are destructive enough to need separate design.

## Dependencies

- **pi-core** (hard peer dep): TasksAccess type contract + registry, agent-mode, session state, workspace state + worktree operations, skill-tracker, catalog, model-aliases

## Type contracts

`TasksAccess`, `TaskStatus`, `Task`, `ReviewState`, `GoalCycle` are owned by pi-core (`pi-core/platform/tasks-access.ts`). Pi-tasks implements `TasksAccess` and registers it into pi-core's registry. Companion and swarm observe via `getTasksAccess()` (returns null if pi-tasks not installed).

## Installation

```bash
pi install /path/to/pi-tasks
```

Installed automatically by `install.py`.
