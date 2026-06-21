---
name: agents
description: "Delegate bounded work to named or ad-hoc agents, track active work, and collect results."
---

# Agents

Use this skill to delegate bounded work to agents while you keep working.

Use these tools for agent delegation; if agents are unavailable, they return a tool error:
- `dispatch_agent({ agent?, task, name? })` — start an agent. The returned handle is the `agentId` in the tool result details.
- `wait_for_agent({ handles: string | string[], timeout_s? })` — wait for one or more agent ids. `timeout_s` defaults to 600.
- `list_agents({ awaitable?: true })` — list visible agents in your current scope. `awaitable` filters to agents with a current run you dispatched.

## Choosing an agent

Default to the narrowest agent that fits:
- **Named read-only agents** (`scout`, `devils-advocate`, `code-clarity-specialist`, `docs-specialist`, `security-specialist`, `testing-specialist`) may fan out for investigation, search, review, and second opinions.
- **worker** is the only mutative agent and requires an active execution worktree. Never run more than one `worker` concurrently against the same worktree.
- **Ad-hoc agents** are read-only by tool allowlist. Use them only for narrow tasks when no named agent fits.

Do not dispatch agents for trivial one-step work you can do directly.

## Handle and wait semantics

- Public handles are agent ids; do not expose private run or execution ids.
- Pass the `agentId` returned by `dispatch_agent` as `handles` to `wait_for_agent`.
- Only the session that dispatched an agent's current run can wait on that agent id. Other callers see `unknown`.
- A timed-out wait reports still-running handles as `running`; it does not cancel the agent.
- `list_agents` returns safe metadata only, not prompts, results, env, or spawn specs.
- Agents cannot message each other. `wait_for_agent` is only for returning results to the dispatcher.
- Delegation depth is capped; if nested dispatch is rejected, continue without spawning another agent.

## Write the brief

A subagent receives no conversation history. Include:
- a concrete objective and expected output
- relevant file paths or modules
- constraints and decisions already made
- explicit acceptance criteria and done definition

## Integration

Review subagent output critically. The parent agent remains responsible for validating evidence, making decisions, applying any changes, and communicating results.
