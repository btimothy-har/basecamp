# pi-companion

Basecamp companion — session snapshot hooks, tmux panes, and analysis registration.

## What it does

- **Session snapshots**: writes session state snapshots for the companion dashboard to consume — a per-session file plus a process-scoped live snapshot the dashboard follows across session/cwd changes
- **Tmux panes**: manages the companion tmux pane lifecycle (create once, verify liveness on session start and recreate if the pane was killed, kill on quit)
- **Analysis registration**: hooks companion analysis into session lifecycle (writes analysis.json)
- **Companion-active flag**: sets pi-core's `isCompanionActive` flag for companion analysis/pane state

The **Python companion TUI** (Textual dashboard, PydanticAI analyzer, daemon client) lives in `pi-companion/tui/`.

## Dependencies

- **pi-core** (hard peer dep): workspace state, agent-mode, skill-tracker, session state, companion-active flag
- **pi-ui** (devDependency): `buildTitleContext` utility for analysis context

## Observation pattern

Companion reads task state from pi-tasks via `getTasksAccess()` (from pi-core's registry). If pi-tasks isn't installed, `getTasksAccess()` returns null and the snapshot omits task progress.

## Installation

```bash
pi install /path/to/pi-companion
```

Installed automatically by `install.py`.
