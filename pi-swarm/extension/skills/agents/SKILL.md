---
name: agents
description: "Delegate bounded work to named or ad-hoc agents, track active work, and collect results."
---

# Agents

Use this skill to delegate bounded work to agents while you keep working.

Use these tools for agent delegation and collaboration; if agents are unavailable, they return a tool error:
- `dispatch_agent({ agent?, task, name?, agent_handle? })` — start or retask a dispatchable async worker and return a public `agent_handle`.
- `wait_for_agent({ handles: string | string[], timeout_s? })` — wait for one or more awaitable dispatch handles. `timeout_s` defaults to 600.
- `list_agents({ awaitable?: true })` — list visible dispatchable agents in your current scope. `awaitable` filters to agents with a current run you dispatched. Sessions are intentionally excluded.
- `ask_agent({ agent_handle, question, timeout_s? })` — ask an agent by its known public handle a question and get its answer back. Forks the target read-only when its thread is available; never interrupts or steers it.
- `message_agent({ agent_handle, message, interrupt? })` — send a one-way persistent message to an agent by its known public handle across sessions. Returns daemon acceptance (`message_id`/status) only; no recipient answer is included.
- `message_status({ message_id, wait_until_delivery?, timeout_s? })` — check delivery lifecycle for a `message_agent` message. Immediate by default; with `wait_until_delivery: true`, waits only for terminal delivery status (`queued`, `failed`, `unavailable`, or `unknown`).

## Choosing an agent

Default to the narrowest agent that fits:
- **Named read-only agents** (`scout`, `devils-advocate`, `code-clarity-specialist`, `docs-specialist`, `security-specialist`, `testing-specialist`) may fan out for investigation, search, review, and second opinions.
- **worker** is the only mutative agent and requires an active execution worktree. Never run more than one `worker` concurrently against the same worktree.
- **Ad-hoc agents** are read-only by tool allowlist. Use them only for narrow tasks when no named agent fits.

Do not dispatch agents for trivial one-step work you can do directly.

## Handles and capabilities

- Public handles are canonical `agent_handle` aliases; do not expose private `agent_id`, `run_id`, or execution ids.
- Every registered daemon node can have the same handle shape, including root/session agents and dispatched workers.
- Capability is separate from identity:
  - **messageable**: agents and sessions can receive `message_agent` when reachable by relationship or addressed by their known public handle.
  - **askable**: agents and sessions can be asked when reachable by relationship or addressed by their known public handle, and the daemon can fork their thread.
  - **dispatchable/retaskable**: only worker agents returned by `list_agents`; sessions and ask answerers are not dispatch targets.
  - **awaitable**: only current primary runs dispatched by this caller; sessions are not awaitable.
- Relationship words such as `parent`, `child`, and `peer` are display labels only. They are not routable target handles. Do not send to `parent`; send to the canonical handle.
- `list_agents` is a dispatch/wait directory, not a message-target directory. It intentionally excludes sessions, even though sessions can be messageable/askable when their handle is known.
- Pass the handle returned by `dispatch_agent` as `handles` to `wait_for_agent`.
- Only the session that dispatched an agent's current run can wait on that handle. Other callers see `unknown`.
- A timed-out wait reports still-running handles as `running`; it does not cancel the agent.
- `list_agents` returns safe metadata only, not prompts, private ids, results, env, or spawn specs.
- Retask by passing an existing dispatchable `agent_handle` to `dispatch_agent`; retasks are rejected while that handle's current run is active, and changing the agent type requires a new handle.
- Delegation depth is capped; if nested dispatch is rejected, continue without spawning another agent.

## Asking another agent

`ask_agent({ agent_handle, question, timeout_s? })` consults another askable agent without disturbing it:
- It **forks** the target's thread into a separate, read-only answerer, asks your question against the target's accumulated context, and returns the answer. The target's own session and run are never modified.
- It is **synchronous**: the call returns the answer (or an error/timeout) — you do not get a handle to manage.
- **Contact is by reachability or known handle**: you may ask an ancestor (your parent chain), a descendant, a sibling (same parent cohort), or any agent whose known public handle you already hold (for example, from a launch record). A handle you do not know returns "no agent available" without revealing whether it exists. A known public handle is a contact address only — it does not let you list, inspect, or wait on that agent.
- Parent/root sessions are askable by canonical handle when forkable; they are still not dispatchable or awaitable worker targets.
- Each ask is recorded as its own run (typed `ask`), visible in run history/observability but excluded from `list_agents`.

Use it for clarification and second opinions ("what did you conclude about X, and why?"), not to redirect what another agent is doing.

## Messaging another agent

`message_agent({ agent_handle, message, interrupt? })` sends a durable one-way message to another messageable agent:
- The target is a canonical handle. Parent/session relationship labels are shown in received content, but they are not aliases.
- It returns promptly when the daemon accepts or rejects the message. The result includes `message_id` and acceptance status only.
- It does **not** wait for recipient delivery, a delivery acknowledgement, or an answer. If the recipient responds, that response is a separate `message_agent` call; use `ask_agent` only when you want a read-only fork answer instead of persistent collaboration.
- `interrupt: true` requests interrupt/steer delivery; omit it for a normal follow-up.
- Contact is by reachability or known handle, as with `ask_agent`; a handle you do not know is reported as `unknown` without private ids, and a known public handle never widens directory, transcript, or wait access.
- Delivered content is rendered as `Message from <handle> (<relation>):`, for example `Message from quiet-badger-3dc450 (parent):`.

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
