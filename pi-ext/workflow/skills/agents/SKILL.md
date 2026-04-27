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

### 4. Integrate the result

Review the subagent output critically. Use it to inform your response, next steps, or integration work, but do not treat delegated output as authority.
