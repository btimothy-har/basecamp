---
name: agents
description: "Dispatch subagents via the agent tool. Invoke when work can be parallelized into independent tasks, or when the user asks to delegate work."
argument-hint: "<task description>"
---

# Agents

Delegate tasks to subagents using the `agent` tool. Subagents run synchronously — output is returned as the tool result.

## Input

$ARGUMENTS

## Process

### 1. Choose an agent

Browse available agents with `/agents`.

| Agent | Best for |
|-------|----------|
| **investigate** | Codebase investigation and context gathering |
| **planner** | Breaking down requirements into implementation steps |
| **worker** | Hands-on code changes, refactors, feature implementation |
| **docs-reviewer** | Documentation accuracy and completeness |
| **security-reviewer** | Injection, auth, secrets, input validation |
| **test-reviewer** | Test coverage gaps, edge cases, assertion design |
| **simplification-reviewer** | Complexity reduction, redundancy, clarity |
| *(ad-hoc)* | One-off tasks that don't fit a predefined agent |

Agents are discovered from two sources: user (`~/.pi/agents/`) and builtin definitions.

### 2. Build the task

Write a **self-contained brief**. The subagent has no conversation history — the task must carry everything:

- Clear, specific objective
- Relevant file paths, modules, or context already discovered
- Constraints or decisions already made
- What "done" looks like

### 3. Dispatch

Using the `agent` tool:

```
agent({ agent: "investigate", task: "Investigate the auth module — find token refresh flow, session management, and middleware chain. Key entry: src/auth/index.ts" })
```

Ad-hoc (no agent definition):
```
agent({ task: "Fix the null check in auth.ts:142", name: "fix-null" })
```

The tool blocks until the subagent completes and returns its output.

### 4. Use the result

The subagent's full output is returned as the tool result. Reason about the findings, incorporate them into your response, or use them to plan next steps.

## Model selection

Each agent declares a model strategy in its frontmatter:

| Strategy | Meaning |
|----------|---------|
| **inherit** | Uses the parent session's current model. Can be overridden via `model` param. |
| **default** | Uses pi's default model. Cannot be overridden. |
| *explicit* (e.g. `claude-sonnet-4-20250514`) | Always uses that model. Cannot be overridden. |

Override only works with `inherit` agents:

```
agent({ agent: "worker", task: "...", model: "anthropic/claude-opus-4-20250514" })
```

Use stronger models for complex architectural work. Use faster models for simple investigation.
