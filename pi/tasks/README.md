# tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, the `plan()` handoff, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `plan()` tool with structured plan review, draft logic, plan skill guard, worktree choices for implementation handoff, and `/show-plan` to view the current plan (the `plan()` tool is hard-blocked in copilot sessions)
- **Workflow skills**: `gather`, `planning` SKILL.md content (the `agents` skill lives in the swarm context)

> **Note**: The workstream domain (`launch_workstream`, `list_workstreams`, `set_workstream_status`, and the `pi --workstream` startup flag) is its own domain (`pi/workstreams/`), persisted in the daemon's SQLite store. The agent tools (`dispatch_agent`/`wait_for_agent`/`list_agents`) belong to the `#core/swarm` primitive.

## Functional smoke cleanup

For manual workstream smoke tests, use an obviously disposable label such as `functional-known-handle-smoke` and verify only the behavior under test: staging, `pi --workstream` agent attachment, known-handle `message_agent`, and known-handle `ask_agent` when the session is forkable.

Cleanup is manual by design:

1. Close the Herdr pane opened for the smoke workstream.
2. Remove the smoke worktree and branch using the normal reviewed git/worktree workflow for this repo.
3. If the smoke workstream record is clearly identified, remove it from the daemon's SQLite store or close it with `set_workstream_status`.

Do not add cleanup automation casually. Worktree deletion, branch deletion, and workstream-record mutation are destructive enough to need separate design.

## Structure

One feature, organized by function (not sub-features):

- **`schemas/`** — the shared data models (`task.ts`, `plan.ts`); the import-nothing leaf.
- **`lifecycle/`** — the durable goal/task state machine: runtime, goal-cycle operations, persistence, and widget.
- **`workflows/`** — the stateless `plan()` procedures: `draft.ts`, `review/`, `handoff/` (incl. `runHandoff`).
- **`tools/`** — the thin agent-facing surface: `task-tools.ts`, `plan-tool.ts`, `commands.ts`, `guards.ts`, `render.ts`. Wired by the composition root; depends downward on the layers below.

## Dependencies

- **core** (`#core/*`): agent-mode (+ copilot), session state, workspace service + worktree setup, skill-tracker, host paths/config

## Type contracts

`TaskStatus`, `Task`, `ReviewState`, `TasksState`, `GoalCycle`, and the plan models (`PlanDraft`, …) live in `pi/tasks/schemas/`. Types needed outside the domain are exported through `#tasks/index.ts`; mutation remains behind the task tools and lifecycle runtime.
