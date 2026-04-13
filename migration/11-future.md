# 11 — Future: Simplify State Management

**Not part of the initial migration.** Do this after everything runs on pi.

## Opportunity

The current architecture uses a long `BASECAMP_*` env var chain:

1. `core/` launch computes values (project name, repo, scratch dir, paths)
2. `build_session_settings()` writes them into a Claude settings.json `env` block
3. Claude injects them into `process.env`
4. Shell hook scripts (now TypeScript handlers) read them back out
5. Worker dispatch bulk-forwards all `BASECAMP_*` vars to child panes

With pi, the extension runs in-process. It has direct access to `ctx.cwd`, `ctx.sessionManager`, `pi.exec()`, and can hold state in TypeScript variables. Much of this chain becomes unnecessary.

## What Could Change

| Current env var | Could become | Notes |
|----------------|-------------|-------|
| `BASECAMP_PROJECT` | Extension derives from launch config or cwd | Still needed by `worker` CLI (Python) |
| `BASECAMP_REPO` | `pi.exec("git", ["rev-parse", ..."])` at session_start | Already computed in lifecycle.ts |
| `BASECAMP_SCRATCH_DIR` | Computed and held in extension state | Skills still reference it via bash |
| `BASECAMP_SETTINGS_FILE` | Potentially unnecessary | Only used to pass settings to child sessions |
| `BASECAMP_SYSTEM_PROMPT` | Extension reads from cache or ctx | Needed for worker prompt inheritance |
| `BASECAMP_CONTEXT_FILE` | Extension reads directly | Already done in lifecycle.ts |
| `BASECAMP_OBSERVER_ENABLED` | Extension checks observer config file | Already done in observer.ts |
| `BASECAMP_INBOX_DIR` | Extension manages inbox internally | No shell scripts reading it anymore |
| `BASECAMP_WORKER_NAME` | Still needed as env var | Workers are separate processes |
| `BASECAMP_WORKER_DIR` | Still needed as env var | Workers are separate processes |
| `BASECAMP_REFLECT` | Extension flag or pi flag | Passed at launch |

## Blocking Dependencies

The env vars can't be fully removed until:

1. **Worker operations** (`core/src/core/worker/operations.py`) are migrated — they read `BASECAMP_PROJECT`, `CLAUDE_SESSION_ID`, `BASECAMP_SYSTEM_PROMPT`, `BASECAMP_SETTINGS_FILE` and build launcher scripts referencing the Claude CLI
2. **Handoff** (`core/src/core/handoff.py`) is migrated — same pattern, reads env vars to build child session commands
3. **Worker communication** (`core/src/core/worker/communication.py`) is migrated — reads `BASECAMP_PROJECT`, `BASECAMP_WORKER_NAME`
4. **Skills** that reference env vars in bash commands are updated

## Approach

Phase 1: Move config into a JSON file that `basecamp launch` writes and the extension reads at `session_start`. This replaces `build_session_settings()` and the env var injection. The extension holds the parsed config in memory.

Phase 2: Migrate worker/handoff to use pi's extension APIs (custom tools, `sendUserMessage`, `ctx.newSession`) instead of spawning CLI processes. This is the big win — workers become extension-managed rather than CLI-managed.

Phase 3: Remove remaining env var dependencies from skills (replace with extension-provided context).
