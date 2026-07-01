# pi-tasks

Basecamp task lifecycle + planning — goal tracking, task state machine, `/plan` command, and workflow skills.

## What it does

- **Task tools**: `update_goal`, `create_tasks`, `start_task`, `complete_task`, `get_task`, `annotate_task`, `delete_task` — persistent goal/task tracking with a below-editor widget
- **Planning**: `/plan` command with structured plan review, draft logic, plan skill guard, legacy task plans, and PR-sized workstream plans
- **Workflow skills**: `gather`, `planning` SKILL.md content (`agents` skill moved to pi-swarm)

The sync in-process agent tool has been removed in the cutover. pi-swarm/extension now provides the sole agent tool (daemon-backed `dispatch_agent`/`wait_for_agent`/`list_agents`).

## Planning modes

`plan()` accepts exactly one execution topology:

- `tasks` — the existing single-lane plan shape. On approval, Basecamp creates a goal cycle, tracks ordered tasks, and uses the existing implementation handoff/worktree flow.
- `workstreams` — PR-sized independent lanes. Each workstream has `id`, `label`, `scope`, `outcome`, `boundaries`, optional `worktreeSlug`, and optional `dependsOn`. Workstreams cannot contain nested `tasks`; choose distinct slugs for ready streams to avoid derived label collisions. Dependency cycles and self-dependencies are rejected.

On workstream approval, Basecamp uses supervisor mode once at least one workstream dispatch is active, validates dependency references, computes the initial ready set, provisions one Basecamp-owned worktree/branch per ready stream, runs setup for newly created ready worktrees, and dispatches ready streams through the pi-core agent-launcher seam registered by pi-swarm. A single approval launches at most 5 new ready workstreams. Blocked streams are recorded but not provisioned. The launch receipt is returned and persisted under `~/.pi/basecamp/workstreams/<session-id>.json`, including each dispatched stream's agent handle and worktree. Resubmitting or revising the same approved plan reuses already-dispatched receipts for the same derived worktree instead of launching duplicate workers. Worktree creation, setup, or launch can fail per stream and should be inspected from the approved result. Setup-failed streams are not retried automatically because the existing worktree may be incomplete. Dispatch success means the daemon accepted the worker launch; workstream agents own their own local task lists and report progress separately.

Workstream outputs are PR-sized units of work. This phase launches only the initial ready wave; blocked streams do not auto-start later. The coordinator does not merge to `main` automatically; use normal PRs or an explicit future integration workflow when streams need to be combined. When Herdr is available, ready dispatched workstream worktrees are opened with `herdr worktree open --no-focus --json` as a best-effort display side effect only.

## Dependencies

- **pi-core** (hard peer dep): TasksAccess type contract + registry, agent launcher registry, agent-mode, session state, workspace state + worktree operations, skill-tracker, catalog, model-aliases

## Type contracts

`TasksAccess`, `TaskStatus`, `Task`, `ReviewState`, `GoalCycle` are owned by pi-core (`pi-core/platform/tasks-access.ts`). Pi-tasks implements `TasksAccess` and registers it into pi-core's registry. Companion and swarm observe via `getTasksAccess()` (returns null if pi-tasks not installed).

## Installation

```bash
pi install /path/to/pi-tasks
```

Installed automatically by `install.py`.
