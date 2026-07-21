# companion

Basecamp Companion owns the session snapshots and side-pane lifecycle for the Python Textual TUI.

## What it does

- **Session snapshots**: writes a per-session snapshot plus a process-scoped live snapshot that follows session and cwd changes
- **Companion panes**: launches `basecamp companion tui` in Herdr when its pane environment is available, falling back to tmux; skips subagents and non-UI sessions
- **Herdr pane metadata**: reports display-only title/status metadata to the current Herdr Pi pane without taking agent lifecycle authority
- **Companion-active flag**: sets core's `isCompanionActive` state while the side pane is live

The Python TUI lives in `src/basecamp/companion/` and starts in Diff mode. Its body cycle is Diff → Files → Swarm. Diff content is read from local Git; Files browses the worktree/main/scratch roots; Swarm reads the daemon's safe run and message projections.

## Dependencies

- **core** (`#core/*`): workspace state, agent mode, skill tracker, session state, and the companion-active flag
- **tasks** (`#tasks/index.ts`): `getTasksReader` + `TaskStatus` for live task-state observation in snapshots

Companion reads task state through `getTasksReader()`. Until Tasks registers its implementation, the reader is null and snapshots omit task progress.

Herdr is optional. If its environment is absent, Companion uses tmux when available; otherwise the pane stays off. Pane creation failures show a warning and disable the pane for that session start. Metadata failures are silent.

Metadata targets only `HERDR_PANE_ID` with source `basecamp.pi`. It reports the session title, display agent, and short custom status within Herdr's field limits. It does not call `herdr pane report-agent`, rename Herdr workspaces/tabs, or manage async-agent panes.
