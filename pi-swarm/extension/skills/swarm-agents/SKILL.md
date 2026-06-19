---
name: swarm-agents
description: "Use async daemon sub-agents for fan-out and long-running delegation."
---

# Swarm Agents

Use this skill to run async delegatees while you keep working. It exposes only daemon tooling:

- `dispatch_agent` — dispatch an async agent and receive an `agent_id` handle.
- `list_agents` — list visible same-root async agents.
- `wait_for_agent` — wait for one or more async handles.

The synchronous, blocking `agent` tool from the main Basecamp `agents` skill can still be used as a separate fallback when fan-out is unnecessary.

## Delegation Guidance

Split work into bounded dispatches with clear scope and done criteria.

Use agents by task shape:
- **scout** for investigation, dependency tracing, broad code search, and context gathering.
- **devils-advocate** for contrarian second opinions on briefs, assumptions, conclusions, and proposed directions.
- **worker** for contained implementation with clear scope and acceptance criteria.
- **specialists** for focused review: clarity, docs, security, testing, SQL, or data concerns when available.
- **ad-hoc** only for a narrow read-only question that no named agent fits.

## Async Daemon Tools

Use async tools when you want fan-out or want to keep reasoning while agents run:

1. `dispatch_agent({ agent?, task, name? })` starts an async agent and returns an **agent handle** (`agent_id`).
2. `list_agents({ awaitable?: true })` lists same-root agents with safe metadata and an `awaitable` flag.
3. `wait_for_agent({ handles, timeout_s? })` waits on one or more async agent handles.

Important semantics:
- Public handles are agent ids. Do not treat private run/execution ids as user-facing handles.
- One agent has one primary active run at a time.
- `wait_for_agent` is dispatcher-owned: only the node that dispatched an agent's current primary run can wait on it.
- Missing or unauthorized agents appear as `unknown`; this avoids leaking whether another handle exists.
- `list_agents` is read-only directory visibility, not messaging. It does not expose prompts, results, errors, env, spawn specs, or private run ids.
- Async message/reply tools are future work; do not use `wait_for_agent` as a peer-message reply mechanism.

## Process

### 1. Review available agents

Review available agents in the capabilities index (named and ad-hoc definitions).

Choose the narrowest agent that fits the job:
- **Named read-only agents** — use for exploration, research code search, reviews, and second opinions.
- **worker** — use for contained code changes with explicit scope and acceptance criteria.
- **ad-hoc** only for narrow read-only questions.

### 2. Write the brief

The subagent has no conversation history. Make the task self-contained:
- Clear, specific objective
- Relevant file paths or modules
- Constraints and decisions already made
- Explicit done criteria

### 3. Dispatch

Using `dispatch_agent`:

```json
{ "agent": "scout", "task": "Investigate the auth module: find token refresh flow, session management, and middleware chain. Key entry: src/auth/index.ts" }
```

Ad-hoc dispatch:

```json
{ "task": "Summarize how auth errors are handled in src/auth", "name": "auth-errors" }
```

### 4. Integrate the result

Review subagent output critically. Use it to inform your response, next steps, or implementation work, but do not treat delegated output as authority.