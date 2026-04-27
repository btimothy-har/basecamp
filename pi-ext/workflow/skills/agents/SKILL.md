---
name: agents
description: "Select a subagent, write a self-contained brief, dispatch it, and integrate the result."
---

# Agents

Delegate bounded work through the `agent` tool. Keep user communication, requirement clarification, final integration, and cross-cutting decisions in the parent agent. Subagents run synchronously and return their output as the tool result.

## Process

### 1. Inspect available agents

Use `discover({ type: "agents" })` to inspect available agents and their descriptions.

Choose the narrowest agent that fits the job:
- **Investigation, planning, or review agents** — use for read-only exploration, research, code search, and second opinions.
- **Implementation agents** — use for contained code changes with clear scope and acceptance criteria.
- **Ad-hoc dispatch** — use when no named agent fits the task.

### 2. Write the brief

The subagent has no conversation history. Make the task self-contained:
- Clear, specific objective
- Relevant file paths, modules, or context already discovered
- Constraints or decisions already made
- Explicit done criteria

### 3. Dispatch

Using the `agent` tool:

```
agent({ agent: "scout", task: "Investigate the auth module — find token refresh flow, session management, and middleware chain. Key entry: src/auth/index.ts" })
```

Ad-hoc dispatch:

```
agent({ task: "Fix the null check in auth.ts:142", name: "fix-null" })
```

### Parallel dispatch

Multiple `agent` tool calls in the same assistant turn run concurrently. Use this for independent code searches, reviews, or option exploration. Do not use parallel dispatch when tasks depend on each other or for unsafe same-cwd mutations. Each tool call is still synchronous and returns a result; this is not background async execution.

### 4. Integrate the result

Review the subagent output critically. Use it to inform your response, next steps, or integration work, but do not treat delegated output as authority.

## Async Dispatch

Read-only agents can run in the background with `async: true`. The tool returns immediately with a handle ID, and the result is delivered automatically when the agent completes.

### When to use async

- **Long investigations** that don't block your current work
- **Multiple independent reviews** dispatched in parallel while you continue coding
- **Background research** where you don't need the result immediately

### Constraints

- **Read-only agents only** — agents with `write` or `edit` tools are blocked from async dispatch
- **No ad-hoc agents** — only named agents with explicit tool restrictions
- **Results auto-delivered** — when complete, the result appears as a message that triggers a new turn

### Examples

Fire-and-forget:

```
agent({ agent: "scout", task: "Find all usages of the deprecated auth API", async: true })
```

Multiple background agents:

```
agent({ agent: "scout", task: "Investigate the payment module", async: true })
agent({ agent: "code-clarity-specialist", task: "Review src/api/routes.ts", async: true })
```

Check status of running background agents:

```
agent_status()
agent_status({ id: "agent-abc123" })
```
