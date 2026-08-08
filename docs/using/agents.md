# Agents & Subagents

Basecamp's primary session can dispatch subagents that run alongside yours, each in its own isolated workspace. Scouts investigate the codebase, reviewers critique a change, and a worker makes edits on a branch you merge. You watch every dispatched run from a global dashboard.

## Agent Types

Every named agent is report-only: it investigates or critiques and returns a report, but writes nothing to your tree.

### General purpose

- **`scout`** — investigates the codebase and returns structured findings for follow-up work.
- **`general-reviewer`** — correctness, logic, control and data flow, edge cases, design fit.
- **`devils-advocate`** — a contrarian second opinion on a brief, assumption, or conclusion.

### Specialists

- **`security-specialist`** — injection, auth, secrets, input validation, data exposure.
- **`testing-specialist`** — coverage gaps, edge cases, mock and assertion quality.
- **`code-clarity-specialist`** — simplification, structure, redundancy, pattern alignment.
- **`conventions-specialist`** — project rules, language and framework idioms, repo patterns.
- **`data-model-specialist`** — dbt and SQL model structure, grain, lineage, dimensional modeling.
- **`integration-specialist`** — cross-layer contracts, producer and consumer parity, migrations.
- **`docs-specialist`** — factual accuracy, completeness, clarity, long-term value.

## Workers

A dispatch with no named agent runs as a worker in deliverable posture. It mints an `agent/<handle>` branch from your clean HEAD, commits its change, and leaves the branch for you to integrate with `git merge agent/<handle>`. A worker needs a clean checkout: a dirty HEAD fails the dispatch with commit-first guidance.

## How dispatch works

Every dispatched agent runs in its own transient git worktree, isolated from your session. Report agents get a branchless, detached copy of your current state (uncommitted work included) and leave nothing behind; their report is the deliverable. Workers branch and commit, as above. Workspaces are removed automatically when a run ends, so commits are the only durable output of a run.

A session with no repository has no worktree to isolate, so its dispatches run report-only with no write tools.

For the dispatch primitive, agent lifecycle, and teardown rules, see [The Agent-Dispatch Model](../architecture/agent-dispatch.md).

## Watching agents: the dashboard

Open the global, read-only session dashboard from any directory:

```bash
basecamp agents
```

The command starts or reuses the single Basecamp hub, mints a 30-second one-time browser login over the owner-only daemon socket, and opens the dashboard. If the system browser cannot be opened, it prints the short-lived fallback URL instead. Run the command again when browser authentication expires.

The dashboard groups top-level Root, Workstream, and Copilot sessions by repository and worktree. It always includes every connected root, including sessions with no child agents, plus the five newest disconnected roots seen within the last 24 hours. An explicit **Load 5 more sessions** control expands disconnected history up to 50 roots; the selected session stays pinned while eligible. Filters cover repository, worktree, kind, live status, agent status, and agent type. Session pages show bounded goal-cycle/task history and recursive agent topology; public-handle agent pages show ancestry, descendants, current task, recent allowlisted activity, skills, previews, and at most three assistant messages. Polling pauses while the page is hidden and retains the last safe in-memory snapshot during a transient failure or busy refresh.

## Dashboard security boundary

The browser surface is deliberately narrower than the daemon:

- It binds only `127.0.0.1:47658`; the port is fixed and a collision disables the dashboard without stopping the UDS hub.
- It exposes no dispatch, cancel, messaging, mutation, workstream-management, or daemon WebSocket routes.
- Browser payloads omit private IDs, paths, session files, prompts/specs, environment data, report tokens, raw tool inputs/results, hidden thinking, and full result/error bodies.
- Authentication state and bootstrap nonces exist only in hub memory. The loopback HTTP cookie is host-only, `HttpOnly`, and `SameSite=Strict`; no login secret is written to disk.
- The 24-hour disconnected-session window and 50-root loader ceiling are display rules, not retention policy. Older SQLite rows are left untouched, and live roots remain visible regardless of age.

This is a single-user localhost surface, not a remote dashboard: there is no configurable bind address, TLS layer, CORS, or multi-user authorization. For the dual-app topology, auth lifecycle, and safe read model, see [Hub Daemon & Dashboard Topology](../architecture/hub-daemon.md).
