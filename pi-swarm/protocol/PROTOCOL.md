# Pi Swarm Daemon Protocol

Protocol version: `14`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":14,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 14`, the daemon sends an `error` frame with `code: "protocol_version"` and closes the connection.
- The extension treats the protocol as a client-visible capability gate, not only a frame-shape version. A version mismatch restarts the host daemon during ensure-daemon.

## Transport

- HTTP over Unix domain socket (UDS):
  - `GET /health` → `{"status":"ok","protocol":14}`
  - `GET /runs/summary?root_id=<id>` returns safe agent-level observability for the companion dashboard.
  - `GET /runs/messages?root_id=<id>&agent_handle=<handle>` returns selected-agent assistant message detail for the companion dashboard.
- WebSocket over UDS:
  - `/ws`
  - First inbound frame must be `register`.
  - On success daemon replies with `registered`.

The socket lives under `~/.pi/basecamp/swarm/daemon.sock` and is restricted to the local user.

## Identity model

The public daemon-agent identity is `agent_handle`, a readable path-safe alias such as `mossy-otter-a1b2c3`. Top-level sessions and dispatched agents use the same handle shape; there is no `session-` prefix and no routable `parent` alias. Relationship words such as `parent`, `child`, and `peer` are display metadata only. Generated handles are type-free; use the separate `agent_type` field for agent definition metadata.

`agent_id` is a private durable UUID-like daemon identity. It remains the primary key for sessions, report authorization, process bookkeeping, and child `BASECAMP_AGENT_ID` values. It may appear in trusted extension-daemon frames, but LLM-facing tools must not present it as the handle.

`run_id` is a private execution correlation id used only by daemon internals and reporting frames:
- `dispatch` / `dispatch_ack` correlate a spawn request.
- `telemetry` and `result_report` authenticate/report the active execution.
- process reaping and run history use the private id.

LLM-facing tools should not present `run_id` or `agent_id` as user handles. Capability is separate from identity: `message_agent` and `ask_agent` may target visible session or worker handles, while `dispatch_agent`, retask, `wait_for_agent`, and `list_agents` stay task-run oriented.

The daemon enforces one primary active run per dispatchable agent. `agents.current_run_id` points at the latest primary run, including terminal runs, so `wait_for_agent(agent_handle)` can retrieve final results until a later primary run replaces it. Retasking an existing handle is conservative: the current run must already be terminal, `agent_type` / `run_kind` for that handle are immutable, and session/ask handles are rejected as non-dispatchable.

## Frame types

Canonical example fixtures live in `pi-swarm/protocol/frames/*.json`.

### `register` client → daemon

Registers the current top-level session or transient agent process.

Important fields:
- `node_id`: internal caller identity. For async agents this is the private `agent_id`.
- `agent_handle`: public alias for the registered node. Current clients send this for both root sessions and async agents.
- `parent_id`: parent node, or `null` for a root session.
- `role`: `session` or `agent`.
- `session_name`, `depth`, `cwd`: safe directory/observability metadata.

### `dispatch` client → daemon

Requests a transient process for an agent.

Important fields:
- `run_id`: private request/execution correlation id.
- `agent_id`: private durable agent identity. If omitted, daemon may mint one as a fallback.
- `agent_handle`: public readable handle for dispatch/list/wait UX. When it matches an existing session or ask-only row, dispatch is rejected as non-dispatchable.
- `agent_type` and `run_kind`: immutable per handle after the first dispatch.
- `model`: public display model selected for the agent run. If the extension uses Pi's default model, it sends/stores `default`.
- `spec`: opaque TypeScript-authored spawn spec.
- `spec.fork_from`: optional; a target agent handle/id. When present, the daemon resolves it to the target's session file and forks it (pi --fork) into a new read-only answerer session — used by the agent 'ask' capability. Omitted/null for normal dispatch.

New run rows persist `dispatcher_id` as the registered `node_id` that sent `dispatch`.

### `dispatch_ack` daemon → client

Acknowledges a dispatch request by private `run_id`.

Statuses:
- `spawned`
- `rejected` with `reason`, including `depth_cap`, `spawn_failed`, `active_run_exists`, `duplicate_agent_handle`, `agent_type_mismatch`, or `not_dispatchable`.

### `telemetry` agent → daemon

Reports progress events for a private run. Authorized by `run_id`, private `agent_id`, and the per-run report token.

### `result_report` agent → daemon

Reports terminal execution result for a private run. Authorized the same way as telemetry.

### `wait` client → daemon

Waits for one or more public agent handles:

```json
{
  "type": "wait",
  "v": 14,
  "agent_ids": [],
  "agent_handles": ["mossy-otter-a1b2c3"],
  "mode": "all",
  "timeout_s": 30
}
```

`agent_ids` remains for internal/backward-compatible callers. New LLM-facing callers should send `agent_handles`.

Authorization is strict and dispatcher-owned: the requester may wait only when its registered `node_id` equals the `dispatcher_id` on the target agent's current primary run. Session handles are not primary-run targets and return `unknown`.

Unauthorized, missing, no-current-run, or non-awaitable agents are returned as `unknown`. They do not block and do not reveal whether the handle exists.

### `wait_result` daemon → client

Returns one result per requested agent handle:

- `completed` / `failed`: terminal result/error for an authorized current primary run.
- `running`: authorized current primary run is still non-terminal after timeout.
- `unknown`: missing, unauthorized, no current primary run, or non-awaitable (including session handles) from the caller's perspective.

Result items contain `agent_handle` for handle-based requests and do not expose private `run_id`. `agent_id` may be present for legacy/id-based requests inside trusted extension-daemon plumbing and must not be shown as the public handle.

### `list_agents` client → daemon

Requests a safe directory of agents visible under the caller's root session:

```json
{
  "type": "list_agents",
  "v": 14,
  "request_id": "list-001",
  "awaitable": true
}
```

`request_id` correlates the response. `awaitable: true` filters to agents whose current primary run the caller may wait on. Omitted or `false` returns all same-root non-session, non-ask agents. This is not a complete message-target directory; sessions remain excluded even when messageable by canonical handle.

### `list_agents_result` daemon → client

Returns same-root agent directory rows:

- `agent_handle`
- `agent_type`
- `run_kind`
- `parent_id`
- `role`
- `session_name`
- `depth`
- `status`: `idle`, `pending`, `running`, `completed`, or `failed`
- `awaitable`

Rows also carry the private `agent_id` for trusted extension retasking plumbing; LLM-facing `list_agents` output strips it. The directory excludes private run ids, prompts, full results, errors, spawn specs, env, and cwd.

### `peer_message` client → daemon

Requests store-backed asynchronous peer message delivery to a public messageable agent handle.

Important fields:
- `request_id`: public request correlation id for the immediate acknowledgement.
- `target_handle`: recipient public handle. It may identify a visible session/root agent or a dispatched agent; it is never a relationship alias such as `parent`.
- `message`: message text to deliver.
- `interrupt`: optional boolean, default `false`; when true, delivery may interrupt the recipient if the runtime supports it.

The request does not expose or require private `agent_id` or `run_id` values. Missing and unauthorized targets both resolve to `unknown` without leaking existence.

### `peer_message_ack` daemon → client

Acknowledges acceptance of a `peer_message` request. This is acceptance only; it must not wait for recipient delivery or an answer.

Fields:
- `request_id`: echoes the peer-message request correlation id.
- `message_id`: stored message id, or `null` when no message was accepted.
- `status`: `accepted` or `unknown`.
- `error`: optional/nullable acceptance error detail.

### `peer_message_delivery` daemon → agent

Delivers an accepted peer message to the recipient agent.

Fields:
- `message_id`: stored message id.
- `from_handle`: sender public handle, or `null` when unavailable.
- `from_relation`: sender relationship from the recipient's perspective: `self`, `parent`, `ancestor`, `child`, `descendant`, `peer`, or `unknown`.
- `message`: message text.
- `interrupt`: whether this delivery should interrupt the recipient.

Recipient clients render injected content as `Message from <handle> (<relation>):`. The handle is the only routable identity; the relation label is display-only.

### `peer_message_delivery_ack` agent → daemon

Acknowledges recipient-side delivery handling.

Fields:
- `message_id`: stored message id.
- `status`: `queued` when the recipient queued the message, or `failed` when it could not.
- `error`: optional/nullable failure detail.

### `message_status` client → daemon

Requests delivery lifecycle status for a stored peer message.

Fields:
- `request_id`: caller-generated id used to correlate the status response.
- `message_id`: stored message id.
- `wait_until_delivery`: optional boolean; when true, the daemon may wait for a terminal delivery state or timeout.
- `timeout_s`: optional wait timeout in seconds.

### `message_status_result` daemon → client

Returns delivery lifecycle status only; it carries no recipient answer or response fields.

Fields:
- `request_id`: echoes the `message_status` request id.
- `message_id`: stored message id.
- `status`: `accepted`, `sent`, `queued`, `failed`, `unavailable`, or `unknown`.
- `error`: optional/nullable lifecycle error detail.
- `created_at`, `sent_at`, `queued_at`, `failed_at`: nullable timestamp strings when known.

For `wait_until_delivery`, terminal delivery states are `queued`, `failed`, `unavailable`, and `unknown`. `accepted` and `sent` are non-terminal.

### `GET /runs/summary`

Returns companion Swarm observability under the requested root session.

Query parameters:
- `root_id` (required): root session agent id whose subtree is summarized.
- `limit` (optional, default `5`): maximum number of agent rows to return. The daemon clamps this to `0`–`100`.

Response schema:
- `root_id`: requested root id.
- `counts`: run status counts for scoped run history: `pending`, `running`, `completed`, `failed`, `total`.
- `agents`: one safe row per same-root non-session agent, ordered by current-run/agent recency.
- `session_active`: whether the root session is currently registered.

Each summary row contains:
- `agent_handle`, `agent_id_short`, `agent_type`, `model`, `role`, `session_name`.
- `agent_id_short`: deterministic short suffix derived from the private agent id for display disambiguation. The raw private `agent_id` is not included.
- `model`: public display model stored from dispatch; legacy rows with no stored model project `default`.
- `status`: one of `idle`, `pending`, `running`, `completed`, or `failed`.
- `result_preview`, `error_preview`, `exit_code`, `created_at`, `started_at`, `ended_at`.
- `task`: safe projection from `~/.pi/basecamp/tasks/<agent-id>.json`, or `null` if absent/invalid. It contains sanitized `goal`, `progress: {completed, deleted, total}`, canonical bounded `task_plan` entries (`index`, `label`, `status`), and `current_task` (`index`, `label`, `status`, `description`, `notes`). Task status values are `pending`, `active`, `completed`, and `deleted`; deleted tasks are omitted from `task_plan` but counted in `progress.deleted`.
- `recent_activity`: bounded telemetry projection containing only allowlisted display fields: event `kind`, `seq`, daemon `timestamp`, `category`, `label`, `snippet`, `toolName`, `isError`, `turnIndex`, and `toolCount`. Current event kinds are `tool_call`, `tool_result`, `assistant_output`, `thinking`, `agent_result`, plus compatible `tool_execution_start`, `tool_execution_end`, and `turn_end`.

Summary rows do not include private `run_id`, private `agent_id`, report tokens, prompts, full results, errors, spawn specs, env, cwd, raw telemetry payloads/args/outputs, raw tool call ids, visible/model message text beyond reporter-sanitized snippets, or hidden model thinking. Display strings are control/ANSI stripped and length capped.

### `GET /runs/messages`

Returns companion Swarm message detail for one selected async agent under the requested root session. This endpoint is intended for selected-agent detail panes, not routine all-agent summary polling.

Query parameters:
- `root_id` (required): root session agent id whose subtree scopes the lookup.
- `agent_handle` (required): public agent handle to display.
- `limit` (optional, default `3`): maximum number of messages. The daemon clamps this to `0`–`3`.

Response schema:
- `root_id`: requested root id.
- `agent_handle`: requested public agent handle.
- `messages`: latest visible assistant messages for the selected agent's current run, ordered oldest-to-newest within the returned window. Each message contains only `kind`, `seq`, daemon `timestamp`, `label`, and full visible assistant `text`.

Message detail is subtree-validated by `root_id` + `agent_handle`. It excludes private `run_id`, raw private `agent_id`, report tokens, prompts, user/system/developer messages, raw tool args/results, env, cwd, spawn specs, hidden thinking, and chain-of-thought. Message text is visible assistant output only; ANSI/control characters are stripped while newlines are preserved. `/runs/summary` remains snippet-only.

### `error` daemon → client

Reports protocol/parse errors and closes the WebSocket for fatal frame errors. Current codes include:

- `protocol_version`
- `invalid_frame`
- `invalid_register`

## Manual smoke shape

A minimal client flow is:

1. Connect to `/ws` over the UDS.
2. Send `register` with `v: 14`.
3. Send `dispatch` with private `run_id` / `agent_id` and public `agent_handle`.
4. Use the `agent_handle` with `wait` or discover agents through `list_agents`.
