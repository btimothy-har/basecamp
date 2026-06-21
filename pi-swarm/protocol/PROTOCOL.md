# Pi Swarm Daemon Protocol

Protocol version: `9`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":9,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 9`, the daemon sends an `error` frame with `code: "protocol_version"` and closes the connection.
- The extension treats the protocol as a client-visible capability gate, not only a frame-shape version. A version mismatch restarts the host daemon during ensure-daemon.

## Transport

- HTTP over Unix domain socket (UDS):
  - `GET /health` → `{"status":"ok","protocol":9}`
  - `GET /runs/summary?root_id=<id>` returns safe agent-level observability for the companion dashboard.
- WebSocket over UDS:
  - `/ws`
  - First inbound frame must be `register`.
  - On success daemon replies with `registered`.

The socket lives under `~/.pi/basecamp/swarm/daemon.sock` and is restricted to the local user.

## Identity model

The public async-agent identity is `agent_handle`, a readable path-safe alias such as `scout-mossy-otter-a1b2c3`.

`agent_id` is a private durable UUID-like daemon identity. It remains the primary key for sessions, report authorization, process bookkeeping, and child `BASECAMP_AGENT_ID` values. It may appear in trusted extension-daemon frames, but LLM-facing tools must not present it as the handle.

`run_id` is a private execution correlation id used only by daemon internals and reporting frames:
- `dispatch` / `dispatch_ack` correlate a spawn request.
- `telemetry` and `result_report` authenticate/report the active execution.
- process reaping and run history use the private id.

LLM-facing tools should not present `run_id` or `agent_id` as user handles. `dispatch_agent` returns an `agent_handle`, `wait_for_agent` accepts agent handles, and `list_agents` renders an agent directory by handle.

The daemon enforces one primary active run per agent. `agents.current_run_id` points at the latest primary run, including terminal runs, so `wait_for_agent(agent_handle)` can retrieve final results until a later primary run replaces it. Retasking an existing handle is conservative: the current run must already be terminal, and `agent_type` / `run_kind` for that handle are immutable.

## Frame types

Canonical example fixtures live in `pi-swarm/protocol/frames/*.json`.

### `register` client → daemon

Registers the current top-level session or transient agent process.

Important fields:
- `node_id`: internal caller identity. For async agents this is the private `agent_id`.
- `agent_handle`: optional public alias for async agents.
- `parent_id`: parent node, or `null` for a root session.
- `role`: `session` or `agent`.
- `session_name`, `depth`, `cwd`: safe directory/observability metadata.

### `dispatch` client → daemon

Requests a transient process for an agent.

Important fields:
- `run_id`: private request/execution correlation id.
- `agent_id`: private durable agent identity. If omitted, daemon may mint one as a fallback.
- `agent_handle`: public readable handle for dispatch/list/wait UX.
- `agent_type` and `run_kind`: immutable per handle after the first dispatch.
- `spec`: opaque TypeScript-authored spawn spec.

New run rows persist `dispatcher_id` as the registered `node_id` that sent `dispatch`.

### `dispatch_ack` daemon → client

Acknowledges a dispatch request by private `run_id`.

Statuses:
- `spawned`
- `rejected` with `reason`, including `depth_cap`, `spawn_failed`, `active_run_exists`, `duplicate_agent_handle`, or `agent_type_mismatch`.

### `telemetry` agent → daemon

Reports progress events for a private run. Authorized by `run_id`, private `agent_id`, and the per-run report token.

### `result_report` agent → daemon

Reports terminal execution result for a private run. Authorized the same way as telemetry.

### `wait` client → daemon

Waits for one or more public agent handles:

```json
{
  "type": "wait",
  "v": 9,
  "agent_ids": [],
  "agent_handles": ["scout-mossy-otter-a1b2c3"],
  "mode": "all",
  "timeout_s": 30
}
```

`agent_ids` remains for internal/backward-compatible callers. New LLM-facing callers should send `agent_handles`.

Authorization is strict and dispatcher-owned: the requester may wait only when its registered `node_id` equals the `dispatcher_id` on the target agent's current primary run.

Unauthorized, missing, or no-current-run agents are returned as `unknown`. They do not block and do not reveal whether the handle exists.

### `wait_result` daemon → client

Returns one result per requested agent handle:

- `completed` / `failed`: terminal result/error for an authorized current primary run.
- `running`: authorized current primary run is still non-terminal after timeout.
- `unknown`: missing or unauthorized from the caller's perspective.

Result items contain `agent_handle` for handle-based requests and do not expose private `run_id`. `agent_id` may be present for legacy/id-based requests inside trusted extension-daemon plumbing and must not be shown as the public handle.

### `list_agents` client → daemon

Requests a safe directory of agents visible under the caller's root session:

```json
{
  "type": "list_agents",
  "v": 9,
  "request_id": "list-001",
  "awaitable": true
}
```

`request_id` correlates the response. `awaitable: true` filters to agents whose current primary run the caller may wait on. Omitted or `false` returns all same-root non-session agents.

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

### `GET /runs/summary`

Returns companion-dashboard observability under the requested root session:

- `counts`: run status counts for scoped run history.
- `agents`: one safe row per same-root non-session agent, keyed by `agent_handle` and current-run status/previews.
- `session_active`: whether the root session is currently registered.

Each summary row may include:
- `task`: safe projection from `~/.pi/basecamp/tasks/<agent-id>.json`, or `null` if absent/invalid. It contains only sanitized `goal`, `progress`, bounded `tasks`/`task_plan` entries (`index`, `label`, `status`), and `current_task` (`index`, `label`, `status`, `description`, `notes`). Deleted tasks are omitted from the plan but counted in progress.
- `recent_activity`: bounded telemetry projection containing only allowlisted display fields: event `kind`, `seq`, timestamp, `toolName`, and `turnIndex`.
- `latest_message`: currently `null`; no safe explicit visible-message source is exposed yet.

Summary rows do not include private `run_id`, private `agent_id`, report tokens, prompts, full results, errors, spawn specs, env, cwd, raw telemetry payloads/args/outputs, or hidden model thinking. Display strings are control/ANSI stripped and length capped.

### `error` daemon → client

Reports protocol/parse errors and closes the WebSocket for fatal frame errors. Current codes include:

- `protocol_version`
- `invalid_frame`
- `invalid_register`

## Manual smoke shape

A minimal client flow is:

1. Connect to `/ws` over the UDS.
2. Send `register` with `v: 9`.
3. Send `dispatch` with private `run_id` / `agent_id` and public `agent_handle`.
4. Use the `agent_handle` with `wait` or discover agents through `list_agents`.
