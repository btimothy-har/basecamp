# Subagents

Use the `agents` skill for agent selection and async daemon dispatch guidance:

```js
skill({ name: "agents" })
dispatch_agent({ agent: "scout", task: "Investigate the auth module" }) // returns an agent handle
list_agents({ awaitable: true })
wait_for_agent({ handles: "<agent-handle>" })
```

Built-in agents: `scout`, `worker`, `devils-advocate`, `security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`, `integration-specialist`.

In a repo-backed session, every dispatched agent runs in its own transient workspace. Report agents (scouts, reviewers) get branchless detached copies of your current state — uncommitted work included — and leave nothing behind; workers mint an `agent/<handle>` branch from your clean HEAD, commit their change, and you `git merge` it. Workspaces are removed automatically when runs end: commits are the only durable output of an agent run. (A non-repo session has no worktree to isolate, so its agents run report-only with no write tools.)
