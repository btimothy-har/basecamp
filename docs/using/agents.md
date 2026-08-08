# Agents & Subagents

Basecamp's primary session can dispatch subagents that run alongside yours, each in its own isolated workspace. Scouts investigate the codebase, reviewers critique a change, and a worker makes edits on its own branch. You watch every dispatched run from a global dashboard.

## Agent Types

Agents come in two postures, decided by what they do to your tree:

- **Report agents** investigate or critique and return findings. They write nothing to your tree.
- **Workers** make changes on separate branches. These branches are prefixed with `agent/` and can be merged independently.

### Report agents

Every named agent is report-only. The general-purpose ones apply to any codebase or change:

- **`scout`** — investigates the codebase and returns structured findings for follow-up work.
- **`general-reviewer`** — correctness, logic, control and data flow, edge cases, design fit.
- **`devils-advocate`** — a contrarian second opinion on a brief, assumption, or conclusion.

The specialists apply a specific lens:

- **`security-specialist`** — injection, auth, secrets, input validation, data exposure.
- **`testing-specialist`** — coverage gaps, edge cases, mock and assertion quality.
- **`code-clarity-specialist`** — simplification, structure, redundancy, pattern alignment.
- **`conventions-specialist`** — project rules, language and framework idioms, repo patterns.
- **`data-model-specialist`** — dbt and SQL model structure, grain, lineage, dimensional modeling.
- **`integration-specialist`** — cross-layer contracts, producer and consumer parity, migrations.
- **`docs-specialist`** — factual accuracy, completeness, clarity, long-term value.

### Workers

A worker is the general-purpose deliverable agent: a dispatch with no named agent makes changes rather than a report. It branches from your clean HEAD and commits there. A worker needs a clean checkout: a dirty HEAD fails the dispatch with commit-first guidance.

## How dispatch works

Every dispatched agent runs in its own transient git worktree, isolated from your session. Report agents get a detached copy of your current state (uncommitted work included) and leave nothing behind; workers branch and commit. Workspaces are removed when a run ends, so commits are the only durable output. A session with no repository has no worktree to isolate, so its dispatches run report-only with no write tools.

For the dispatch primitive, agent lifecycle, and teardown rules, see [The Agent-Dispatch Model](../architecture/agent-dispatch.md).

## Watching agents: the dashboard

Open the global, read-only session dashboard from any directory:

```bash
basecamp agents
```

It opens in your browser with a short-lived login; if no browser is available, it prints the URL instead. Run `basecamp agents` again when the login expires.

The dashboard groups Root, Workstream, and Copilot sessions by repository and worktree, showing every connected session plus the most recent disconnected ones. Filters narrow by repository, worktree, status, and agent type. Session pages show goal and task history with the full agent tree; agent pages show ancestry, current task, skills, and recent activity.

## Dashboard security boundary

The browser surface is deliberately narrower than the daemon:

- It binds only `127.0.0.1:47658`; the port is fixed and a collision disables the dashboard without stopping the UDS hub.
- It exposes no dispatch, cancel, messaging, mutation, workstream-management, or daemon WebSocket routes.
- Browser payloads omit private IDs, paths, session files, prompts/specs, environment data, report tokens, raw tool inputs/results, hidden thinking, and full result/error bodies.
- Authentication state and bootstrap nonces exist only in hub memory. The loopback HTTP cookie is host-only, `HttpOnly`, and `SameSite=Strict`; no login secret is written to disk.
- The 24-hour disconnected-session window and 50-root loader ceiling are display rules, not retention policy. Older SQLite rows are left untouched, and live roots remain visible regardless of age.

This is a single-user localhost surface, not a remote dashboard: there is no configurable bind address, TLS layer, CORS, or multi-user authorization. For the dual-app topology, auth lifecycle, and safe read model, see [Hub Daemon & Dashboard Topology](../architecture/hub-daemon.md).
