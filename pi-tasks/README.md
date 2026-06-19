# pi-tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, `/plan` command, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `annotate_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `/plan` command with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff
- **Workflow skills**: `gather`, `planning` SKILL.md content (`agents` skill moved to pi-swarm)

The sync in-process agent tool has been removed in the cutover. pi-swarm/extension now provides the sole agent tool (daemon-backed `dispatch_agent`/`wait_for_agent`/`list_agents`).

## Dependencies

- **pi-core** (hard peer dep): TasksAccess type contract + registry, agent-mode, session state, workspace state + worktree operations, skill-tracker, catalog, model-aliases

## Type contracts

`TasksAccess`, `TaskStatus`, `Task`, `ReviewState`, `GoalCycle` are owned by pi-core (`pi-core/platform/tasks-access.ts`). Pi-tasks implements `TasksAccess` and registers it into pi-core's registry. Companion and swarm observe via `getTasksAccess()` (returns null if pi-tasks not installed).

## Installation

```bash
pi install /path/to/pi-tasks
```

Installed automatically by `install.py`.
