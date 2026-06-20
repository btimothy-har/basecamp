# Pi Swarm Daemon Protocol

Protocol version: `6`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":6,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 6`, the daemon sends an `error` frame with `code: "protocol_version"` and closes the connection.
- The extension treats the protocol as a client-visible capability gate, not only a frame-shape version. A version mismatch restarts the host daemon during ensure-daemon.

## Transport

- HTTP over Unix domain socket (UDS):
  - `GET /health` → `{"status":"ok","protocol":6}`
  - `GET /runs/summary?root_id=<id>` returns safe run-summary observability.
- WebSocket over UDS:
  - `/ws`
  - First inbound frame must be `register`.
  - On success daemon replies with `registered`.

The socket lives under `~/.pi/basecamp/swarm/daemon.sock` and is restricted to the local user.

## Public identity model

The public async-agent handle is `agent_id`.

`run_id` is a private execution correlation id used only by daemon internals and reporting frames:
- `dispatch` / `dispatch_ack` correlate a spawn request.
- `telemetry` and `result_report` authenticate/report the active execution.
- process reaping and run history use the private id.

LLM-facing tools should not present `run_id` as the handle. `dispatch_agent` returns an agent handle, `wait_for_agent` accepts agent handles, and `list_agents` returns an agent directory.

The daemon enforces one primary active run per agent. `agents.current_run_id` points at the latest primary run, including terminal runs, so `wait_for_agent(agent_id)` can retrieve final results until a later primary run replaces it.

## Frame types

Canonical example fixtures live in `pi-swarm/protocol/frames/*.json`.

### `register` client → daemon

Registers the current top-level session or transient agent process.

Important fields:
- `node_id`: caller identity. For async agents this is the `agent_id`.
- `parent_id`: parent node, or `null` for a root session.
- `role`: `session` or `agent`.
- `session_name`, `depth`, `cwd`: safe directory/observability metadata.

### `dispatch` client → daemon

Requests a transient process for an agent.

Important fields:
- `run_id`: private request/execution correlation id.
- `agent_id`: stable public agent identity. If omitted, daemon may mint one as a fallback.
- `spec`: opaque TypeScript-authored spawn spec.

New run rows persist `dispatcher_id` as the registered `node_id` that sent `dispatch`.

### `dispatch_ack` daemon → client

Acknowledges a dispatch request by private `run_id`.

Statuses:
- `spawned`
- `rejected` with `reason`, including `depth_cap`, `spawn_failed`, or `active_run_exists`.

### `telemetry` agent → daemon

Reports progress events for a private run. Authorized by `run_id`, `agent_id`, and the per-run report token.

### `result_report` agent → daemon

Reports terminal execution result for a private run. Authorized the same way as telemetry.

### `wait` client → daemon

Waits for one or more agent handles:

```json
{
  "type": "wait",
  "v": 6,
  "agent_ids": ["agent-001"],
  "mode": "all",
  "timeout_s": 30
}
```

Authorization is strict and dispatcher-owned: the requester may wait only when its registered `node_id` equals the `dispatcher_id` on the target agent's current primary run.

Unauthorized, missing, or no-current-run agents are returned as `unknown`. They do not block and do not reveal whether the handle exists.

### `wait_result` daemon → client

Returns one result per requested agent id:

- `completed` / `failed`: terminal result/error for an authorized current primary run.
- `running`: authorized current primary run is still non-terminal after timeout.
- `unknown`: missing or unauthorized from the caller's perspective.

The result items contain `agent_id`; they do not expose private `run_id`.

### `list_agents` client → daemon

Requests a safe directory of agents visible under the caller's root session:

```json
{
  "type": "list_agents",
  "v": 6,
  "request_id": "list-001",
  "awaitable": true
}
```

`request_id` correlates the response. `awaitable: true` filters to agents whose current primary run the caller may wait on. Omitted or `false` returns all same-root non-session agents.

### `list_agents_result` daemon → client

Returns same-root agent directory rows:

- `agent_id`
- `parent_id`
- `role`
- `session_name`
- `depth`
- `status`: `idle`, `pending`, `running`, `completed`, or `failed`
- `awaitable`

The directory excludes private run ids, prompts, full results, errors, spawn specs, env, and cwd.

### `error` daemon → client

Reports protocol/parse errors and closes the WebSocket for fatal frame errors. Current codes include:

- `protocol_version`
- `invalid_frame`
- `invalid_register`

## Manual smoke shape

A minimal client flow is:

1. Connect to `/ws` over the UDS.
2. Send `register` with `v: 6`.
3. Send `dispatch` with a private `run_id` and public `agent_id`.
4. Use the `agent_id` with `wait` or discover agents through `list_agents`.
