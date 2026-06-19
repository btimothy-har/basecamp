# pi-core

The always-present foundation for basecamp. A pi-installed extension containing the primitive registries, session lifecycle, workspace state, and shared type contracts that every other basecamp module depends on.

## What it does

- **Platform registries** (process-scoped via `globalThis` + `Symbol.for`): exec/cwd provider, capability catalog, skill invocation tracker, model-alias resolve hooks, workspace state + worktree operations
- **Environment contract** (`platform/env.ts`): typed `BASECAMP_*` env var getters/setters, companion-active flag, workspace state hooks for pi-workspace override
- **Session lifecycle**: agent-mode state machine (analysis/planning/supervisor/executor), session start (state load + mode restore), session shutdown, chat compaction
- **State persistence**: file-backed session state (`~/.pi/session-state/<session-id>.json`) with fork inheritance
- **Capabilities**: the `skill()` tool, SKILL.md content parsing, catalog providers
- **Model aliases**: native config provider (`~/.pi/model-aliases/config.json`) + `/model-alias` commands
- **Escalate**: the `escalate` tool — pause and ask the user for a decision (primary sessions only)
- **Workspace defaults**: git detection at session_start (repo, remote, branch from `process.cwd()`); worktree operations (list/activate/attach) as thin git wrappers. Pi-workspace overrides these defaults with basecamp-config-aware values via the hook registry.
- **Shared type contracts**: `TasksAccess`, `Task`, `TaskStatus`, `ReviewState`, `GoalCycle` — owned here so pi-tasks implements, and pi-companion/pi-swarm observe without a runtime dep on pi-tasks

## Architecture

Pi-core is the only hard dependency of every pluggable module. The dependency graph is strictly one-directional:

```
pi-core ← pi-ui, pi-workspace, pi-tasks, pi-git, pi-engineering, pi-companion, pi-swarm
```

No pluggable module imports from another pluggable module at runtime. Cross-module observation of optional state (companion→tasks, swarm→tasks) uses `import type` (erased) + dynamic `import()` guarded by try/catch.

## Workspace override model

Pi-core provides working defaults (git detection from cwd, `process.cwd()` as cwd provider). Pi-workspace, when installed, overrides these via the hook registry — registering a config-aware `WorkspaceService` and cwd provider. Last-writer-wins via the `Symbol.for("basecamp.*")` globalThis pattern. Without pi-workspace, sessions run with git defaults and no project context.

## Installation

```bash
pi install /path/to/core/pi
```

Installed automatically by `install.py`. Must be installed before any other basecamp package.
