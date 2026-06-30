---
name: agents
description: "Delegate bounded work to named or ad-hoc agents, track active work, and collect results."
---

# Agents

Use this skill to delegate bounded work to agents while you keep working.

Use these tools for agent delegation; if agents are unavailable, they return a tool error:
- `dispatch_agent({ agent?, task, name?, agent_handle? })` — start an agent and return a public `agent_handle`.
- `wait_for_agent({ handles: string | string[], timeout_s? })` — wait for one or more agent handles. `timeout_s` defaults to 600.
- `list_agents({ awaitable?: true })` — list visible agents in your current scope. `awaitable` filters to agents with a current run you dispatched.
- `ask_agent({ agent_handle, question, timeout_s? })` — ask a visible agent a question and get its answer back. Forks the target read-only; never interrupts or steers it.
- `message_agent({ agent_handle, message, interrupt? })` — send a one-way persistent message to a visible agent. Returns daemon acceptance (`message_id`/status) only; no recipient answer is included.
- `message_status({ message_id, wait_until_delivery?, timeout_s? })` — check delivery lifecycle for a `message_agent` message. Immediate by default; with `wait_until_delivery: true`, waits only for terminal delivery status (`queued`, `failed`, `unavailable`, or `unknown`).

## Choosing an agent

Default to the narrowest agent that fits:
- **Named read-only agents** (`scout`, `devils-advocate`, `code-clarity-specialist`, `docs-specialist`, `security-specialist`, `testing-specialist`) may fan out for investigation, search, review, and second opinions.
- **worker** is the only mutative agent and requires an active execution worktree. Never run more than one `worker` concurrently against the same worktree.
- **Ad-hoc agents** are read-only by tool allowlist. Use them only for narrow tasks when no named agent fits.

Do not dispatch agents for trivial one-step work you can do directly.

## Handle and wait semantics

- Public handles are `agent_handle` aliases; do not expose private `agent_id`, `run_id`, or execution ids.
- Pass the handle returned by `dispatch_agent` as `handles` to `wait_for_agent`.
- Only the session that dispatched an agent's current run can wait on that handle. Other callers see `unknown`.
- A timed-out wait reports still-running handles as `running`; it does not cancel the agent.
- `list_agents` returns safe metadata only, not prompts, private ids, results, env, or spawn specs.
- Agents can send one-way persistent messages to visible peers with `message_agent`; this queues a follow-up or interrupt for the recipient but does not include a response. Use `message_status` to check whether the message was accepted/sent/queued/failed/unavailable/unknown.
- Agents can consult a visible agent with `ask_agent` (a read-only fork of the target), and `wait_for_agent` returns a dispatched agent's result to its dispatcher.
- Retask by passing an existing `agent_handle` to `dispatch_agent`; retasks are rejected while that handle's current run is active, and changing the agent type requires a new handle.
- Delegation depth is capped; if nested dispatch is rejected, continue without spawning another agent.

## Asking another agent

`ask_agent({ agent_handle, question, timeout_s? })` consults another agent without disturbing it:
- It **forks** the target's thread into a separate, read-only answerer, asks your question against the target's accumulated context, and returns the answer. The target's own session and run are never modified.
- It is **synchronous**: the call returns the answer (or an error/timeout) — you do not get a handle to manage.
- **Visibility is default-deny**: you may ask only an ancestor (your parent chain), a descendant, or a sibling (same parent cohort). Anything else returns "no agent available" without revealing whether it exists.
- Each ask is recorded as its own run (typed `ask`), visible in run history/observability but excluded from `list_agents`.

Use it for clarification and second opinions ("what did you conclude about X, and why?"), not to redirect what another agent is doing.

## Messaging another agent

`message_agent({ agent_handle, message, interrupt? })` sends a durable one-way message to another visible agent:
- It returns promptly when the daemon accepts or rejects the message. The result includes `message_id` and acceptance status only.
- It does **not** wait for recipient delivery, a delivery acknowledgement, or an answer. If the recipient responds, that response is a separate `message_agent` call; use `ask_agent` only when you want a read-only fork answer instead of persistent collaboration.
- `interrupt: true` requests interrupt/steer delivery; omit it for a normal follow-up.
- Visibility is default-deny, as with `ask_agent`; unknown or unauthorized targets are reported as `unknown` without private ids.

`message_status({ message_id, wait_until_delivery?, timeout_s? })` checks delivery state for a message you can see:
- Without `wait_until_delivery`, it returns the current lifecycle status immediately.
- With `wait_until_delivery: true`, it waits only until terminal delivery state (`queued`, `failed`, `unavailable`, or `unknown`) or timeout. It still never returns an answer.
- Status output is lifecycle-only: `accepted`, `sent`, `queued`, `failed`, `unavailable`, or `unknown`, plus error/timestamps when available.

## Write the brief

A subagent receives no conversation history. Include:
- a concrete objective and expected output
- relevant file paths or modules
- constraints and decisions already made
- explicit acceptance criteria and done definition

## Integration

Review subagent output critically. The parent agent remains responsible for validating evidence, making decisions, applying any changes, and communicating results.
