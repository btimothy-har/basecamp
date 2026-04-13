---
name: dispatch
description: "Dispatch worker agents via the worker tool. Invoke when work can be parallelized into independent tasks, or when the user asks to delegate work."
argument-hint: "<task description>"
---

# Dispatch

Delegate a task to a worker agent using the `worker` tool.

## Input

$ARGUMENTS

## Process

### 1. Choose an agent (or go ad-hoc)

Review available agents with `worker({ action: "list" })` or `/agents`.

| Agent | Best for |
|-------|----------|
| **scout** | Fast codebase investigation, context gathering |
| **planner** | Breaking down requirements into implementation steps |
| **worker** | Hands-on code changes, refactors, feature implementation |
| **reviewer** | Reviewing diffs, checking code quality |
| *(ad-hoc)* | One-off tasks that don't fit a predefined agent |

### 2. Build the task

Write a **self-contained brief**. The worker has no conversation history — the task must carry everything:

- Clear, specific objective
- Relevant file paths, modules, or context already discovered
- Constraints or decisions already made
- What "done" looks like

### 3. Dispatch

Using the `worker` tool:

```
worker({ agent: "scout", task: "Investigate the auth module — find token refresh flow, session management, and middleware chain. Key entry: src/auth/index.ts" })
```

For complex hands-on work (visible Kitty pane, user can observe):
```
worker({ agent: "worker", task: "...", mode: "pane" })
```

For background investigation or review:
```
worker({ agent: "scout", task: "...", mode: "background" })
```

Ad-hoc (no agent definition):
```
worker({ task: "Fix the null check in auth.ts:142", name: "fix-null" })
```

### 4. Verify

```
worker({ action: "list" })
```

## Mode selection

- **pane** (default for `worker` agent) — visible Kitty window. User can observe, intervene. Best for implementation tasks.
- **background** (default for `scout`, `planner`, `reviewer`) — headless. Best for investigation, analysis, review tasks that don't need user interaction.

## Model selection

Workers inherit the agent's default model. Override when needed:

```
worker({ agent: "worker", task: "...", model: "anthropic/claude-opus-4-20250514" })
```

Use stronger models for complex architectural work. Use faster models for simple investigation.
