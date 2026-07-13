# Pi Swarm Daemon Protocol

Protocol version: `21`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":21,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 21`, the daemon sends an `error` frame with `code: "protocol_version"` and closes the connection.
- The extension treats the protocol as a client-visible capability gate, not only a frame-shape version. A version mismatch restarts the host daemon during ensure-daemon.
- v15 adds known-public-handle contact for `peer_message` and fork-`ask`: contact is authorized without a live relationship when the target is addressed by its known public handle (see below).
- v16 adds registered session transcript paths for fork-ask and product-role metadata for peer-message display.
- v17 adds safe current-task previews to `list_agents_result` rows.
- v18 adds cancel-agent request/ack frames and dispatched-run lifecycle hardening: process-group spawn, dispatcher-disconnect grace reaping, and startup reconciliation of orphaned runs.
- v19 adds workstream management frames (`create_workstream`/`attach_workstream_agent`/`update_workstream` + acks) and HTTP GET `/workstreams` read endpoints.
- v20 adds the `thread_report` frame: a top-level session ships its raw `getBranch()` thread to the daemon at end of turn for the companion analyzer (see `docs/design/companion-daemon-broker.md`).
- v21 adds first-class node-identity facets (`repo`, `worktree_label`) to `register`, renames node roles to `agent` (user-facing) / `worker` (backgrounded) derived from `BASECAMP_USER_FACING`, and removes the retired `product_role` (register display role) and `run_kind` (dispatch/list mutative kind) fields along with the agent-role and mutative seams.

## Transport

- HTTP over Unix domain socket (UDS):
  - `GET /health` → `{"status":"ok","protocol":21}`
  - `GET /runs/summary?root_id=<id>` returns safe agent-level observability for the companion dashboard.
  - `GET /runs/messages?root_id=<id>&agent_handle=<handle>` returns selected-agent assistant message detail for the companion dashboard.
  - `GET /workstreams` returns a filtered list of workstreams (query params: `status`, `repo`, `dossier_path`, `query`).
  - `GET /workstreams/{id_or_slug}` returns a single workstream with its joined agent rows.
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

LLM-facing tools should not present `run_id` or `agent_id` as user handles. Capability is separate from identity. Top-level/copilot sessions and started workstream sessions are contactable but not taskable: they may receive `message_agent` and may be asked by canonical handle when the daemon has a forkable session file, but they are not dispatchable, retaskable, awaitable, or listed by `list_agents`. Dispatched worker agents are taskable under the existing dispatcher/retask constraints. Ask answerers are transient and hidden from task directories.

The daemon enforces one primary active run per dispatchable agent. `agents.current_run_id` points at the latest primary run, including terminal runs, so `wait_for_agent(agent_handle)` can retrieve final results until a later primary run replaces it. Retasking an existing handle is conservative: the current run must already be terminal, `agent_type` for that handle is immutable, and session/ask handles are rejected as non-dispatchable.

## Run lifecycle and cleanup

Dispatched agents run as full `pi` processes spawned by the daemon in their own process group (the runner is the group leader), so the daemon can terminate a run's entire process tree with a single group signal (SIGTERM, then SIGKILL after a short escalation window).

Dispatched-run processes are freed three ways so they cannot leak as long-running memory:

- Dispatcher disconnect: when a dispatcher's connection drops, the daemon schedules a grace-period reaper for that `node_id`. If the same node does not re-register within the window, its still-live dispatched runs are terminated, marked `failed` with `error: "dispatcher_disconnected"`, and their waiters are woken. A reconnecting session (reload/resume) cancels the pending reaper and reclaims its in-flight agents. The grace period is `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default `3600`; invalid or negative values fall back to the default). There is no wall-clock cap on run duration — only the disconnect grace.
- Explicit cancellation: the `cancel` / `cancel_ack` frames (below), which cancel the target and its whole dispatch subtree.
- Startup reconciliation: on daemon start every non-terminal run is marked `failed` with `error: "daemon_restart_reconciled"`, and orphaned process groups left by a prior daemon are best-effort killed, gated by an identity check (the group leader's command must match the runner) so a reused process-group id is never signalled.

The daemon is a long-lived shared singleton and does not idle-shut-down by design.

## Frame types

Canonical example fixtures live in `pi/core/hub/protocol/frames/*.json`.

### `register` client → daemon

Registers the current top-level session or transient agent process.

Important fields:
- `node_id`: internal caller identity. For async agents this is the private `agent_id`.
- `agent_handle`: public alias for the registered node. Current clients send this for both root sessions and async agents.
- `parent_id`: parent node, or `null` for a root session.
- `role`: `agent` (user-facing session) or `worker` (fully backgrounded), derived from `BASECAMP_USER_FACING`.
- `session_name`, `depth`, `cwd`: safe directory/observability metadata.
- `session_file`: optional registered transcript file path used only as an ask fork source after authorization succeeds. It is not exposed in LLM-facing tools.
- `repo`: optional canonical `<org>/<name>` repo identity facet for the registered node.
- `worktree_label`: optional active worktree label facet (e.g. `copilot/<slug>`), or empty when no worktree is active.

### `dispatch` client → daemon

Requests a transient process for an agent.

Important fields:
- `run_id`: private request/execution correlation id.
- `agent_id`: private durable agent identity. If omitted, daemon may mint one as a fallback.
- `agent_handle`: public readable handle for dispatch/list/wait UX. When it matches an existing session or ask-only row, dispatch is rejected as non-dispatchable.
- `agent_type`: immutable per handle after the first dispatch.
- `model`: public display model selected for the agent run. If the extension uses Pi's default model, it sends/stores `default`.
- `spec`: opaque TypeScript-authored spawn spec.
- `spec.fork_from`: optional; a target agent handle/id. When present, the daemon resolves it to the target's registered session file or daemon-managed agent session sidecar and forks it (`pi --fork`) into a new read-only answerer session — used by the agent ask capability. Omitted/null for normal dispatch. Resolution by known public handle authorizes the fork-ask across relationships (as with `peer_message`); the private-`agent_id` fallback stays relationship-gated. If no safe fork source exists, the target is reported as unavailable without distinguishing missing, unauthorized, or non-forkable targets.

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

### `thread_report` client → daemon

Ships the top-level session's raw thread to the daemon at end of turn, for the companion analyzer. Authorized by the connection's registered `node_id` (a session identity), not a per-run report token. Fire-and-forget (no ack).

The extension splits `getBranch()` into per-entry `nodes` — `id`, `parent_id`, and the verbatim serialized entry as `entry_json` — so the daemon stores immutable nodes (keyed by `id`, inserting only new ones) without parsing pi content. `session_id` and `session_file` are pi's own session id and `.jsonl` transcript path; the daemon records them on the per-session head alongside `leaf_id`, and reconstructs the active branch by walking `parent_id` from `leaf_id`.

```json
{
  "type": "thread_report",
  "v": 21,
  "node_id": "00000000-0000-4000-8000-000000000042",
  "session_id": "session-abc",
  "session_file": "/home/u/.pi/sessions/session-abc.jsonl",
  "leaf_id": "entry-002",
  "nodes": [
    {"id": "entry-001", "parent_id": null, "entry_json": "{…}"},
    {"id": "entry-002", "parent_id": "entry-001", "entry_json": "{…}"}
  ]
}
```

### `wait` client → daemon

Waits for one or more public agent handles:

```json
{
  "type": "wait",
  "v": 21,
  "agent_ids": [],
  "agent_handles": ["mossy-otter-a1b2c3"],
  "mode": "all",
  "timeout_s": 30
}
```

`agent_ids` remains for internal/backward-compatible callers. New LLM-facing callers should send `agent_handles`.

Authorization is strict and dispatcher-owned: the requester may wait only when its registered `node_id` equals the `dispatcher_id` on the target agent's current primary run. Session handles are not primary-run targets and return `unknown`.

Unauthorized, missing, no-current-run, or non-awaitable agents are returned as `unknown`. They do not block and do not reveal whether the handle exists. LLM-facing tools render this as not awaitable or unavailable.

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
  "v": 21,
  "request_id": "list-001",
  "awaitable": true
}
```

`request_id` correlates the response. `awaitable: true` filters to agents whose current primary run the caller may wait on. Omitted or `false` returns all same-root non-session, non-ask agents. This is not a complete message-target directory; sessions remain excluded even when messageable by canonical handle.

### `list_agents_result` daemon → client

Returns same-root agent directory rows:

- `agent_handle`
- `agent_type`
- `parent_id`
- `role`
- `session_name`
- `depth`
- `status`: `idle`, `pending`, `running`, `completed`, or `failed`
- `awaitable`
- `task`: optional safe preview of the current primary run task, sanitized and truncated for display.

Rows also carry the private `agent_id` for trusted extension retasking plumbing; LLM-facing `list_agents` output strips it. LLM-facing display treats handle plus `agent_type` as stable identity and shows task/title metadata separately. The directory excludes private run ids, prompts, full results, errors, spawn specs, env, and cwd.

### `peer_message` client → daemon

Requests store-backed asynchronous peer message delivery to a public messageable agent handle.

Important fields:
- `request_id`: public request correlation id for the immediate acknowledgement.
- `target_handle`: recipient public handle. It may identify a visible session/root agent or a dispatched agent; it is never a relationship alias such as `parent`.
- `message`: message text to deliver.
- `interrupt`: optional boolean, default `false`; when true, delivery may interrupt the recipient if the runtime supports it.

The request does not expose or require private `agent_id` or `run_id` values. Missing and unauthorized targets both resolve to `unknown` without leaking existence.

Contact authorization is satisfied by either relationship reachability (self, ancestor/descendant, or same sibling group) or by addressing the target's known public handle. A known public handle is a routable contact address, not authorization for introspection: it never widens the agent directory (`list_agents`), transcript/run-message access, `wait_for_agent` result ownership, or private `agent_id` routing (which stays relationship-gated). This keeps persisted agent records useful for contact after resume or across user-facing surfaces without leaking hidden agents.

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
- `from_product_role`: optional safe product role display label, such as `copilot` or an agent type.
- `message`: message text.
- `interrupt`: whether this delivery should interrupt the recipient.

Recipient clients render injected content by preferring product role, then structural relation, then a neutral sender label with no `(unknown)` suffix. Example: `Message from <handle> (copilot):` or `Message from <handle> (parent):`. The handle is the only routable identity; product-role and relation labels are display-only.

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

For `wait_until_delivery`, terminal delivery states are `queued`, `failed`, `unavailable`, and `unknown`. `accepted` and `sent` are non-terminal. LLM-facing tools may render `queued` as `queued in recipient session` while preserving the protocol status value.

### `cancel` client → daemon

Requests cancellation of an agent's current run.

Fields:
- `request_id`: caller-generated id used to correlate the ack.
- `target_handle`: public handle of the agent to cancel.

Authorization is subtree-only: the requester may cancel a target only when it dispatched that target directly or transitively (it is an ancestor of the target, or the dispatcher of the target's current run). Unlike `peer_message` / fork-`ask`, a known public handle does NOT authorize cancellation. A successful cancel recurses through the target's dispatch subtree: it marks the current run of the target and each descendant `failed` with `error: "cancelled"`, terminates each tracked process group, and wakes waiters. This stops a cancelled agent's descendants immediately instead of leaving them until their own dispatcher-disconnect grace expires.

### `cancel_ack` daemon → client

Acknowledges a `cancel` request.

Fields:
- `request_id`: echoes the cancel request id.
- `status`: `cancelled` when at least one run in the target's subtree was cancelled by this request; `not_found` when the handle does not resolve; `not_authorized` when the target is outside the requester's dispatch subtree; or `already_terminal` when nothing in the subtree was still running.
- `error`: optional/nullable detail.

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

### `create_workstream` client → daemon

Requests creation of a new workstream in the daemon's SQLite store. The workstream is durable, repo-neutral internal coordination state; worktrees are not persisted (git remains the source of truth, the `copilot/<slug>` worktree name encodes the slug).

Important fields:
- `request_id`: public request correlation id for the immediate acknowledgement.
- `workstream_id`: internal `ws_<uuid>` identity minted by the extension.
- `slug`: globally-unique three-word readable id (the extension generates a collision-free slug; the daemon enforces uniqueness).
- `label`: human-readable workstream label.
- `brief`: workstream brief injected into `pi --workstream` sessions.
- `source_dossier_path`: path to the Logseq dossier work page the workstream points to (one dossier may have many workstreams).
- `constraints`: optional workstream constraints.
- `source_repo_page_path`: optional path to the repository cockpit/page.

### `create_workstream_ack` daemon → client

Acknowledges a `create_workstream` request.

Fields:
- `request_id`: echoes the create-workstream request id.
- `status`: `created` or `slug_conflict`.
- `workstream_id`: the daemon-confirmed workstream id, or `null` on conflict.
- `slug`: the daemon-confirmed slug, or `null` on conflict.
- `error`: optional/nullable error detail.

### `attach_workstream_agent` client → daemon

Attaches the requester's own session as a workstream agent. Every `pi --workstream` session appends a row — additive, concurrent, never overwriting.

Important fields:
- `request_id`: public request correlation id.
- `workstream`: the workstream slug or id to attach to.
- `repo`: the current repo identity (`<org>/<name>`). "Which repos touched" derives from agent rows.
- `worktree_label`: the active worktree label (e.g. `copilot/<slug>`).
- `status`: optional membership status, default `attached` (`attached` | `failed`).
- `error`: optional/nullable error detail for a failed attach.

### `attach_workstream_agent_ack` daemon → client

Acknowledges an `attach_workstream_agent` request.

Fields:
- `request_id`: echoes the attach request id.
- `status`: `attached` or `not_found`.
- `error`: optional/nullable error detail.

### `update_workstream` client → daemon

Requests a workstream status update (open ↔ closed).

Fields:
- `request_id`: public request correlation id.
- `workstream`: the workstream slug or id.
- `status`: `open` or `closed`.

### `update_workstream_ack` daemon → client

Acknowledges an `update_workstream` request.

Fields:
- `request_id`: echoes the update request id.
- `status`: `updated`, `not_found`, or `invalid_status`.
- `error`: optional/nullable error detail.

### `error` daemon → client

Reports protocol/parse errors and closes the WebSocket for fatal frame errors. Current codes include:

- `protocol_version`
- `invalid_frame`
- `invalid_register`

## Manual smoke shape

A minimal client flow is:

1. Connect to `/ws` over the UDS.
2. Send `register` with `v: 21`.
3. Send `dispatch` with private `run_id` / `agent_id` and public `agent_handle`.
4. Use the `agent_handle` with `wait` or discover agents through `list_agents`.
