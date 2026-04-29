---
name: agents
description: "Select a subagent, write a self-contained brief, dispatch it, and integrate the result."
---

# Agents

Delegate bounded work through the `agent` tool. Keep user communication, requirement clarification, final integration, and cross-cutting decisions in the parent agent. Subagents run synchronously and return their output as the tool result.

## Supervisor Delegation

When operating delegation-first, use this skill before non-trivial execution. Split work into bounded dispatches instead of defaulting to direct implementation.

Use agents by task shape:
- **scout** for investigation, dependency tracing, broad code search, and context gathering.
- **worker** for contained implementation with clear scope and acceptance criteria.
- **specialists** for focused review: clarity, docs, security, testing, SQL, or data concerns when available.
- **ad-hoc** only for a narrow read-only question that no named agent fits.

Keep these responsibilities in the parent session:
- User conversation, requirement clarification, and preference decisions.
- Goal/task tracking and drift detection.
- Architecture choices, cross-cutting trade-offs, and final integration.
- Critical review of subagent output; never relay it as authority.

Prefer read-only agents first when the code surface is unclear. Dispatch mutative `worker` agents only after the implementation scope and done criteria are explicit. If you choose not to delegate non-trivial work, state the reason briefly before proceeding.

## Process

### 1. Review available agents

Review the Agents section in the capabilities index for available agents and their descriptions.

Choose the narrowest agent that fits the job:
- **Named read-only agents** — use for exploration, research, code search, review, and second opinions.
- **worker** — the only mutative agent; use for contained code changes with clear scope and acceptance criteria.
- **Ad-hoc dispatch** — sync-only, read-only, and solo; use only when no named read-only agent fits the task.

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
agent({ task: "Summarize how auth errors are handled in src/auth", name: "auth-errors" })
```

### Parallel dispatch

Multiple `agent` tool calls in the same assistant turn run concurrently. Use this only for independent named read-only agents, such as code searches, reviews, or option exploration. Do not include `worker` or ad-hoc dispatch in parallel calls; they must run solo. Each sync tool call still returns a result; this is not background async execution.

### 4. Integrate the result

Review the subagent output critically. Use it to inform your response, next steps, or integration work, but do not treat delegated output as authority.

## Async Dispatch

Read-only agents can run in the background with `async: true`. The tool returns immediately with a handle ID, and the result is delivered automatically when the agent completes.

### When to use async

- **Long investigations** that don't block your current work
- **Multiple independent reviews** dispatched in parallel while you continue coding
- **Background research** where you don't need the result immediately

### Constraints

- **Named read-only agents only** — async dispatch does not support `worker` or ad-hoc agents
- **Parallel-safe with read-only agents** — multiple async named read-only agents can run together
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
