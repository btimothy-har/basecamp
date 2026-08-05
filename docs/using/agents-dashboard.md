# Agents dashboard

Open the global, read-only session dashboard from any directory:

```bash
basecamp agents
```

The command starts or reuses the single Basecamp hub, mints a 30-second one-time browser login over the owner-only daemon socket, and opens the dashboard. If the system browser cannot be opened, it prints the short-lived fallback URL instead. Run the command again when browser authentication expires.

The dashboard groups top-level Root, Workstream, and Copilot sessions by repository and worktree. It always includes every connected root, including sessions with no child agents, plus the five newest disconnected roots seen within the last 24 hours. An explicit **Load 5 more sessions** control expands disconnected history up to 50 roots; the selected session stays pinned while eligible. Filters cover repository, worktree, kind, live status, agent status, and agent type. Session pages show bounded goal-cycle/task history and recursive agent topology; public-handle agent pages show ancestry, descendants, current task, recent allowlisted activity, skills, previews, and at most three assistant messages. Polling pauses while the page is hidden and retains the last safe in-memory snapshot during a transient failure or busy refresh.

The browser surface is deliberately narrower than the daemon:

- It binds only `127.0.0.1:47658`; the port is fixed and a collision disables the dashboard without stopping the UDS hub.
- It exposes no dispatch, cancel, messaging, mutation, workstream-management, or daemon WebSocket routes.
- Browser payloads omit private IDs, paths, session files, prompts/specs, environment data, report tokens, raw tool inputs/results, hidden thinking, and full result/error bodies.
- Authentication state and bootstrap nonces exist only in hub memory. The loopback HTTP cookie is host-only, `HttpOnly`, and `SameSite=Strict`; no login secret is written to disk.
- The 24-hour disconnected-session window and 50-root loader ceiling are display rules, not retention policy. Older SQLite rows are left untouched, and live roots remain visible regardless of age.

This is a single-user localhost surface, not a remote dashboard: there is no configurable bind address, TLS layer, CORS, or multi-user authorization.
