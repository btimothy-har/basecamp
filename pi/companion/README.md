# companion

Basecamp companion — the companion **dashboard integration**: session snapshot hooks, companion panes, and Herdr metadata. It is a pure consumer of hub analysis, not a producer.

## What it does

- **Session snapshots**: writes session state snapshots for the companion dashboard to consume — a per-session file plus a process-scoped live snapshot the dashboard follows across session/cwd changes
- **Companion panes**: opens the companion dashboard in Herdr when the session has `HERDR_ENV=1`, `HERDR_PANE_ID`, and `HERDR_SOCKET_PATH`; falls back to tmux when Herdr is unavailable; skips subagents and non-UI sessions
- **Herdr pane metadata**: reports display-only metadata to the current Herdr Pi pane with `herdr pane report-metadata` so Herdr can show the Basecamp title/status without Basecamp taking agent lifecycle authority
- **Companion-active flag**: sets core's `isCompanionActive` flag for companion pane state

Raw-thread reporting for the analyzer is **not** a companion job: it moved to the core hub connector (`pi/core/hub/thread-reporter.ts` — "connect + report"), because every session feeds the daemon regardless of the dashboard. The **Python companion TUI** (Textual dashboard, daemon client) lives in `src/basecamp/companion/`. Analysis is produced by the daemon (see `docs/design/companion-daemon-broker.md`) and read over `GET /analysis/{session_id}`; the snapshot and goal-cycle panels stay file-sourced.

## Dependencies

- **core** (`#core/*`): workspace state, agent-mode, skill-tracker, session state, and the companion-active flag
- **tasks** (`#tasks/index.ts`): `getTasksReader` + `TaskStatus` — live task-state observation for the snapshot

## Observation pattern

Companion reads task state from the tasks context via `getTasksReader()` (`#tasks/index.ts`). Until tasks registers its implementation, `getTasksReader()` returns null and the snapshot omits task progress.

Herdr is optional. If Herdr env vars are absent, the companion uses the existing tmux fallback when tmux is available; otherwise the pane stays off. Pane creation failures show a warning and disable the companion pane for that session start. Metadata failures are silent.

Metadata targets only the current `HERDR_PANE_ID` with source `basecamp.pi`; it reports the session title, display agent, and short custom status with Herdr's field limits. It does not call `herdr pane report-agent`, rename Herdr workspaces/tabs, or manage async-agent panes.
