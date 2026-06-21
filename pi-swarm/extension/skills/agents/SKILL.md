---
name: agents
description: "Use async daemon agents for fan-out and long-running delegation."
---

# Agents

Use this skill to delegate bounded work to async daemon agents while you keep working.

Available tools:
- `dispatch_agent` — start an async agent and receive an `agent_id` handle.
- `list_agents` — read-only visibility into same-root async agents.
- `wait_for_agent` — wait for one or more dispatched agent ids.

## Delegation guidance

Split work into focused dispatches with clear scope and done criteria.

Choose the narrowest agent that fits:
- **Named read-only agents** (`scout`, `devils-advocate`, specialists) may fan out for investigation, search, review, and second opinions.
- **worker** is mutative. Do not run workers in parallel against the same worktree, or overlap a worker with other agents that may affect the same worktree, until daemon mutation leases exist.
- **ad-hoc** should be narrow and read-only when no named agent fits.

## Write the brief

A subagent receives no conversation history. Include:
- a concrete objective and expected output
- relevant file paths or modules
- constraints and decisions already made
- explicit acceptance criteria and done definition

## Async daemon tools

1. `dispatch_agent({ agent?, task, name? })` starts an async agent and returns an **agent id**.
2. `list_agents({ awaitable?: true })` lists visible same-root agents with safe metadata.
3. `wait_for_agent({ handles, timeout_s? })` waits on one or more agent ids.

Important semantics:
- Public handles are agent ids; do not expose private run or execution ids.
- `wait_for_agent` is dispatcher-owned: only the dispatcher of an agent's current primary run can wait on it.
- `list_agents` is read-only visibility, not messaging. It does not expose prompts, results, errors, env, spawn specs, or private run ids.
- Async message/reply tools are future work; do not use `wait_for_agent` as a peer-message mechanism.

## Integration

Review subagent output critically. The parent agent remains responsible for validating evidence, making decisions, applying any changes, and communicating results.
