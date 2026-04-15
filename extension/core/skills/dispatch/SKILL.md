---
name: dispatch
description: "Dispatch worker agents via the worker tool. Invoke when work can be parallelized into independent tasks, or when the user asks to delegate work."
argument-hint: "<task description>"
---

# Dispatch

Delegate a task to a subagent using the `worker` tool. The subagent runs synchronously — its output is returned as the tool result.

## Input

$ARGUMENTS

## Process

### 1. Choose an agent (or go ad-hoc)

Review available agents with `/agents`.

| Agent | Best for |
|-------|----------|
| **scout** | Fast codebase investigation, context gathering |
| **planner** | Breaking down requirements into implementation steps |
| **worker** | Hands-on code changes, refactors, feature implementation |
| **reviewer** | Reviewing diffs, checking code quality |
| *(ad-hoc)* | One-off tasks that don't fit a predefined agent |

### 2. Build the task

Write a **self-contained brief**. The subagent has no conversation history — the task must carry everything:

- Clear, specific objective
- Relevant file paths, modules, or context already discovered
- Constraints or decisions already made
- What "done" looks like

### 3. Dispatch

Using the `worker` tool:

```
worker({ agent: "scout", task: "Investigate the auth module — find token refresh flow, session management, and middleware chain. Key entry: src/auth/index.ts" })
```

Ad-hoc (no agent definition):
```
worker({ task: "Fix the null check in auth.ts:142", name: "fix-null" })
```

The tool blocks until the subagent completes and returns its output.

### 4. Use the result

The subagent's full output is returned as the tool result. Reason about the findings, incorporate them into your response, or use them to plan next steps.

## Model selection

Each agent declares a model strategy in its frontmatter:

| Strategy | Meaning |
|----------|----------|
| **inherit** | Uses the parent session's current model. Can be overridden via `model` param. |
| **default** | Uses pi's default model. Cannot be overridden. |
| *explicit* (e.g. `anthropic/claude-haiku-4-5`) | Always uses that model. Cannot be overridden. |

Override only works with `inherit` agents:

```
worker({ agent: "worker", task: "...", model: "anthropic/claude-opus-4-20250514" })
```

Use stronger models for complex architectural work. Use faster models for simple investigation.
