---
name: agents
description: "Agent delegation guidance for bounded work, active-run tracking, and result collection."
---

# Agents

Apply this skill to delegate bounded work to agents while you keep working.

Use these tools for agent delegation and collaboration; if agents are unavailable, they return a tool error:
- `dispatch_agent({ agent?, task, name?, agent_handle? })` — start or retask a dispatchable async worker and return a public `agent_handle`.
- `wait_for_agent({ handles: string | string[], timeout_s? })` — wait for one or more awaitable dispatch handles. `timeout_s` defaults to 600.
- `cancel_agent({ agent_handle })` — cancel a running agent you dispatched, stopping it and its entire dispatched subtree. Subtree-only: you can only cancel agents within your own dispatch tree.
- `list_agents({ awaitable?: true })` — list visible dispatchable agents in your current scope. `awaitable` filters to agents with a current run you dispatched. Sessions are intentionally excluded.
- `ask_agent({ agent_handle, question, timeout_s? })` — ask an agent or session by its known public handle and get an answer back when the target is forkable. Forks the target read-only; never interrupts or steers it.
- `message_agent({ agent_handle, message, interrupt? })` — send a one-way persistent message to an agent by its known public handle across sessions. Returns daemon acceptance (`message_id`/status) only; no recipient answer is included.
- `message_status({ message_id, wait_until_delivery?, timeout_s? })` — check delivery lifecycle for a `message_agent` message. Immediate by default; with `wait_until_delivery: true`, waits only for terminal delivery status (`queued`, `failed`, `unavailable`, or `unknown`).

## Choosing an agent

Default to the narrowest agent that fits:
- **Named read-only agents** (`scout`, `devils-advocate`, `code-clarity-specialist`, `docs-specialist`, `security-specialist`, `testing-specialist`) may fan out for investigation, search, review, and second opinions.
- **worker** is the only mutative agent: it works in its **own** isolated worktree (branched from your current HEAD), commits its change to a branch, and reports back — so you can run several `worker`s in parallel. Dispatching a `worker` requires you to be in an execution worktree (it branches from yours).
- **Ad-hoc agents** are read-only by tool allowlist. Use them only for narrow tasks when no named agent fits.

Do not dispatch agents for trivial one-step work you can do directly.

## Handles and capabilities

- Public handles are canonical `agent_handle` aliases; do not expose private `agent_id`, `run_id`, or execution ids.
- Every registered daemon node can have the same handle shape, including root/session agents and dispatched workers.
- Capability is separate from identity:
  - **messageable**: agents and sessions can receive `message_agent` when reachable by relationship or addressed by their known public handle.
  - **askable**: agents and sessions can be asked when reachable by relationship or addressed by their known public handle, and the daemon has a forkable session file.
  - **dispatchable/retaskable**: only worker agents returned by `list_agents`; sessions and ask answerers are not dispatch targets.
  - **awaitable**: only current primary runs dispatched by this caller; sessions are not awaitable.
- Relationship words such as `parent`, `child`, and `peer` are display labels only. They are not routable target handles. Do not send to `parent`; send to the canonical handle.
- `list_agents` is a dispatch/wait directory, not a message-target directory. It intentionally excludes sessions, even though sessions can be messageable/askable when their handle is known.
- Pass the handle returned by `dispatch_agent` as `handles` to `wait_for_agent`.
- Only the session that dispatched an agent's current run can wait on that handle. Other callers see `unknown`.
- A timed-out wait reports still-running handles as `running`; it does not cancel the agent (use `cancel_agent` to stop it).
- `list_agents` returns safe metadata only, not prompts, private ids, results, env, or spawn specs. It displays stable identity as handle plus agent type, with current task/title metadata separate.
- Retask by passing an existing dispatchable `agent_handle` to `dispatch_agent`; retasks are rejected while that handle's current run is active, and changing the agent type requires a new handle.
- Delegation depth is capped; if nested dispatch is rejected, continue without spawning another agent.

## Asking another agent

`ask_agent({ agent_handle, question, timeout_s? })` consults another askable agent without disturbing it:
- It **forks** the target's thread into a separate, read-only answerer, asks your question against the target's accumulated context, and returns the answer. The target's own session and run are never modified.
- It is **synchronous**: the call returns the answer (or an error/timeout) — you do not get a handle to manage.
- **Contact is by reachability or known handle**: you may ask an ancestor (your parent chain), a descendant, a sibling (same parent cohort), or any agent whose known public handle you already hold (for example, from a launch record). An unavailable handle returns `No available agent for that handle.` without revealing whether it exists. A known public handle is a contact address only — it does not let you list, inspect, wait on that agent, or retrieve transcripts.
- Parent/root sessions and started workstream sessions are askable by canonical handle when forkable; they are still not dispatchable, retaskable, awaitable, or listed worker targets.
- Each ask is recorded as its own run (typed `ask`), visible in run history/observability but excluded from `list_agents`.

Use it for clarification and second opinions ("what did you conclude about X, and why?"), not to redirect what another agent is doing.

## Messaging another agent

`message_agent({ agent_handle, message, interrupt? })` sends a durable one-way message to another messageable agent:
- The target is a canonical handle. Parent/session relationship labels are shown in received content, but they are not aliases.
- It returns promptly when the daemon accepts or rejects the message. The result includes `message_id` and acceptance status only.
- It does **not** wait for recipient delivery, a delivery acknowledgement, or an answer. If the recipient responds, that response is a separate `message_agent` call; use `ask_agent` only when you want a read-only fork answer instead of persistent collaboration.
- `interrupt: true` requests interrupt/steer delivery; omit it for a normal follow-up.
- Contact is by reachability or known handle, as with `ask_agent`; an unavailable handle is reported without private ids, and a known public handle never widens directory, transcript, or wait access.
- Delivered content prefers product-role labels, then structural relation, then a neutral no-label fallback. Examples: `Message from quiet-badger-3dc450 (copilot):`, `Message from quiet-badger-3dc450 (parent):`, or `Message from quiet-badger-3dc450:`.

`message_status({ message_id, wait_until_delivery?, timeout_s? })` checks delivery state for a message you can see:
- Without `wait_until_delivery`, it returns the current lifecycle status immediately.
- With `wait_until_delivery: true`, it waits only until terminal delivery state (`queued`, `failed`, `unavailable`, or `unknown`) or timeout. It still never returns an answer.
- Status output is lifecycle-only: `accepted`, `sent`, `queued` (rendered as `queued in recipient session`), `failed`, `unavailable`, or `unknown`, plus error/timestamps when available.

## Write the brief

A subagent receives no conversation history. Include:
- a concrete objective and expected output
- relevant file paths or modules
- constraints and decisions already made
- explicit acceptance criteria and done definition

## Integration

Review subagent output critically — you validate evidence, make decisions, and communicate results.

Read-only agents return findings; you apply any changes yourself. A **worker** instead commits its change to its own branch (reported as `agent-<id>/worker`); its worktree is torn down on finish when clean. To integrate a finished worker:

1. `wait_for_agent` on its handle and read its final report (a PR-style summary of what changed).
2. From your own worktree, `git merge agent-<id>/worker` to bring the change in, resolving any conflicts as normal.
3. Then `git branch -d agent-<id>/worker` to delete the merged branch (allowed — it is not a `git worktree` command). A clean worker **worktree** is removed for you when the agent exits; a dirty residual is preserved for recovery rather than force-deleted. Never run `git worktree remove` (that is blocked, and worktree lifecycle is system-managed).

If a worker's change isn't wanted, do not merge it. A clean worktree is still reclaimed, but the unmerged branch remains until you explicitly delete it.
