# Hub Protocol

Protocol version: `28`

All frames are JSON objects with an envelope:

```json
{"type":"<frame_type>","v":28,...}
```

Version handling:
- The daemon validates `v` on every inbound frame.
- If `v != 28`, the daemon sends an `error` frame with `code: "protocol_version"` and closes the connection.
- The extension treats the protocol as a client-visible capability gate, not only a frame-shape version. A version mismatch restarts the host daemon during ensure-daemon.

Only the current version is speakable; this document specifies it in full. History lives in the repository.

## Transport

- HTTP over Unix domain socket (UDS) at `~/.pi/basecamp/swarm/daemon.sock`, restricted to the local user:
  - `GET /health` → `{"status":"ok","protocol":28}`
  - `GET /runs/summary?root_id=<id>`: compact rows for the in-Pi active-agent widget.
  - `GET /workstreams`: filtered list (query params: `status`, `repo`, `dossier_path`, `query`).
  - `GET /workstreams/{id_or_slug}`: single workstream (including `version`) with joined agent rows and `versions` history array.
  - `POST /dashboard/bootstrap`: mints a 30-second, single-use browser bootstrap URL; only while the dashboard listener is available.
  - `GET /dashboard/snapshot` and `GET /dashboard/messages?root_handle=<handle>&agent_handle=<handle>`: private safe projections, consumed only by the dashboard's fixed-method UDS client.
- WebSocket over UDS at `/ws`: the first inbound frame must be `register`; on success the daemon replies `registered`.

The same hub process owns a separate read-only FastAPI app pre-bound to `127.0.0.1:47658`. Its only routes are `/bootstrap/<nonce>`, `/`, `/assets/<name>`, `/api/snapshot`, and `/api/messages`, all GET-only; no `/ws`, workstream, run-summary, or mutation routes, and it never mounts or proxies the UDS app. Browser sessions require the in-memory bootstrap exchange plus exact Host, Origin/Fetch-Metadata provenance, no-CORS/no-store security headers, and a host-only `HttpOnly; SameSite=Strict` cookie. Dashboard bind/start failure is nonfatal to the UDS server and disables nonce minting.

## Identity model

- **`agent_handle`** is the public identity: a readable path-safe alias such as `mossy-otter-a1b2c3`. Top-level sessions and dispatched agents share the handle shape; there is no `session-` prefix and no routable `parent` alias (`parent`/`child`/`peer` are display metadata only). Generated handles are type-free; use `agent_type` for agent-definition metadata.
- **`agent_id`** is the private durable identity: primary key for sessions, report authorization, process bookkeeping, and child `BASECAMP_AGENT_ID` values. LLM-facing tools must never present it as the handle.
- **`run_id`** is the private execution correlation id, used only by daemon internals and reporting frames. LLM-facing tools do not present it.

Capability is separate from identity. Top-level/copilot sessions and started workstream sessions are contactable but not taskable: they may receive `message_agent` and may be asked by canonical handle when the daemon has a forkable session file, but they are not dispatchable, retaskable, awaitable, or listed by `list_agents`. Dispatched worker agents are taskable under the dispatcher/retask constraints. Ask answerers are transient and hidden from task directories.

The daemon enforces one primary active run per dispatchable agent. `agents.current_run_id` points at the latest primary run (terminal runs included), so `wait_for_agent(agent_handle)` can retrieve final results until a later primary run replaces it. Retasking is conservative: the current run must be terminal, `agent_type` is immutable per handle, and session/ask handles are rejected as non-dispatchable.

## Run lifecycle and cleanup

Dispatched agents run as full `pi` processes in their own process group (the runner is the group leader), so a run's whole process tree is terminated with one group signal (SIGTERM, then SIGKILL after a short escalation window). Processes are freed three ways so they cannot leak:

- **Dispatcher disconnect**: the daemon schedules a grace-period reaper for the dispatcher's `node_id`; if the node does not re-register within the window, its live dispatched runs are terminated, marked `failed` with `error: "dispatcher_disconnected"`, and waiters are woken. A reconnecting session cancels the pending reaper and reclaims its in-flight agents. Grace period: `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default `3600`; invalid or negative falls back). There is no wall-clock run-duration cap; only the disconnect grace.
- **Explicit cancellation**: the `cancel` / `cancel_ack` frames, which cancel the target and its whole dispatch subtree.
- **Startup reconciliation**: on daemon start every non-terminal run is marked `failed` with `error: "daemon_restart_reconciled"`, and orphaned process groups left by a prior daemon are best-effort killed, gated by an identity check (the group leader's command must match the runner) so a reused process-group id is never signalled.

The daemon is a long-lived shared singleton and does not idle-shut-down. Clients coordinate starts through the exclusive `daemon.spawn.lock` contract; each daemon holds a nonblocking process-lifetime `flock` on `daemon.server.lock` before it can unlink or bind the UDS, so a raced/manual second daemon cannot steal the socket.

## Frame types

Canonical example fixtures live in `pi/core/hub/protocol/frames/*.json`.

### `register` client → daemon

Registers the current top-level session or transient agent process.

- `node_id`: internal caller identity; for async agents the private `agent_id`.
- `agent_handle`: public alias for the registered node.
- `parent_id`: parent node, or `null` for a root session.
- `role`: `agent` (user-facing session) or `worker` (fully backgrounded), derived from `BASECAMP_USER_FACING`.
- `session_name`, `depth`, `cwd`: safe display metadata.
- `session_file`: optional registered transcript path, used only as an ask fork source after authorization; never exposed in LLM-facing tools.
- `repo`: optional canonical `<org>/<name>` facet.
- `worktree_label`: optional active worktree label (e.g. `copilot/<slug>`), or `null`.
- `branch`: optional active worktree branch.
- `model`: optional current model id.
- `agent_mode`: optional current mode (`analysis`, `planning`, `work`, `copilot`).

### `session_metadata` client → daemon

Replaces mutable metadata for the authenticated WebSocket's own registered node. No node-id field: the target is the connection's own registration. Fields: `session_name`, `model` (nullable), `agent_mode`, and the workspace facets `repo` / `worktree_label` / `branch` (each nullable; null clears stale persisted metadata).

### `dispatch` client → daemon

Requests a transient process for an agent.

- `run_id`: private request/execution correlation id.
- `agent_id`: private durable identity; daemon may mint one if omitted.
- `agent_handle`: public handle for dispatch/list/wait UX. Matching an existing session or ask-only row is rejected as non-dispatchable.
- `agent_type`: immutable per handle after the first dispatch.
- `model`: display model for the run; `default` when the extension uses Pi's default model.
- `spec`: opaque TypeScript-authored spawn spec.
- `spec.owned_worktree`: optional; the run's own transient worktree. The daemon force-removes it on run exit (normal reap and crash-restart reconcile); uncommitted state is discarded by design; commits are the only durable output of a run.
- `spec.owned_branch` / `spec.branch_base` / `spec.branch_created`: optional; the run's per-agent branch (`agent/<handle>`), the commit OID it started from, and whether this dispatch minted the branch. Only deliverable runs (the `worker` persona) carry a branch; report runs and asks are branchless (`owned_branch` null, `branch_created` false). After worktree removal the daemon deletes `owned_branch` only when `branch_created` is true and `rev-list <branch_base>..<branch>` is empty; a continued or commit-bearing branch always survives teardown.
- `spec.fork_from`: optional; a target agent handle/id. When present, the daemon resolves it to the target's registered session file or daemon-managed agent session sidecar and forks it (`pi --fork`) into a new answerer session (the agent ask capability). Omitted/null for normal dispatch.
- Fork-ask answerer isolation: branchless detached workspace, force-removed at run end; the answerer never mints a branch, so nothing it writes survives. Resolution by known public handle authorizes the fork-ask across relationships (as with `peer_message`); the private-`agent_id` fallback stays relationship-gated. A target with no safe fork source is reported unavailable without distinguishing missing, unauthorized, or non-forkable.

New run rows persist `dispatcher_id` as the registered `node_id` that sent `dispatch`.

### `dispatch_ack` daemon → client

Acknowledges a dispatch by private `run_id`. Statuses: `spawned`, or `rejected` with `reason` (`depth_cap`, `spawn_failed`, `active_run_exists`, `duplicate_agent_handle`, `agent_type_mismatch`, `not_dispatchable`).

### `telemetry` / `result_report` agent → daemon

Progress and terminal-result reports for a private run. Authorized by `run_id`, private `agent_id`, and the per-run report token.

### `wait` client → daemon

Waits for one or more public agent handles:

```json
{
  "type": "wait",
  "v": 28,
  "request_id": "wait-001",
  "agent_ids": [],
  "agent_handles": ["mossy-otter-a1b2c3"],
  "mode": "all",
  "timeout_s": 30
}
```

`agent_handles` is the request surface; `agent_ids` is reserved for internal callers. The daemon runs each wait as its own task and echoes `request_id` on the result, so several waits may be in flight on one connection.

Authorization is strict and dispatcher-owned: the requester may wait only when its `node_id` equals the `dispatcher_id` on the target's current primary run. Session handles are not primary-run targets and return `unknown`. Unauthorized, missing, no-current-run, and non-awaitable agents are all returned as `unknown`: they do not block and do not reveal whether the handle exists.

### `wait_result` daemon → client

One item per requested handle, echoing `request_id`. Items contain `agent_handle` and never private `run_id`; `agent_id` may appear only on legacy `agent_ids`-based requests inside trusted extension-daemon plumbing and must never be surfaced as the public handle:

- `completed` / `failed`: terminal result/error for an authorized current primary run.
- `running`: authorized run still non-terminal after timeout.
- `unknown`: missing, unauthorized, no current primary run, or non-awaitable (including session handles).

### `ping` / `pong` either direction

Application-level keepalive (in addition to the daemon's transport-level websocket pings, 20s/20s). The only correct answer to `{"type":"ping","v":28,"nonce":"n"}` is a `pong` carrying the same nonce. An unsolicited `pong` is inert and must not close the connection.

The daemon also sends `ping` as its **incumbent-liveness probe**: on a duplicate registration for a connected `node_id`, it pings the incumbent and waits for a same-nonce `pong`. A pong keeps the incumbent's session and the newcomer is rejected with `duplicate_node_connection`; only an unanswered probe releases the node id. A completed write is not sufficient evidence (a frozen peer's transport still accepts bytes), which is why an answer is required. Blind takeover is never performed.

### `list_agents` client → daemon

Requests a safe directory of agents visible under the caller's root session. `request_id` correlates the response; `awaitable: true` filters to agents whose current primary run the caller may wait on (omitted/`false` returns all same-root non-session, non-ask agents). This is not a message-target directory: sessions remain excluded even when messageable by handle.

### `list_agents_result` daemon → client

Same-root agent directory rows: `agent_handle`, `agent_type`, `parent_id`, `role`, `session_name`, `depth`, `status` (`idle` | `pending` | `running` | `completed` | `failed`), `awaitable`, and `task` (optional sanitized, truncated preview of the current primary run task). Rows also carry the private `agent_id` for trusted extension retasking plumbing; LLM-facing `list_agents` output strips it. The directory excludes private run ids, prompts, full results, errors, spawn specs, env, and cwd.

### `peer_message` client → daemon

Requests store-backed asynchronous delivery to a public messageable handle.

- `request_id`: correlation id for the immediate acknowledgement.
- `target_handle`: recipient public handle (a visible session/root agent or a dispatched agent; never a relationship alias such as `parent`).
- `message`: message text to deliver.
- `interrupt`: optional boolean, default `false`; when true, delivery may interrupt the recipient if the runtime supports it.

The request never exposes or requires private ids. Missing and unauthorized targets both resolve to `unknown` without leaking existence. Authorization is by relationship reachability (self, ancestor/descendant, or same sibling group) or by addressing the target's known public handle. A known handle is a contact address, not authorization for introspection: it never widens the agent directory, transcript/run-message access, `wait_for_agent` result ownership, or private-id routing (relationship-gated). This keeps persisted records useful for contact after resume without leaking hidden agents.

### `peer_message_ack` daemon → client

Acceptance only; never recipient delivery or an answer. Fields: `request_id` (echo), `message_id` (stored id, or `null` when none accepted), `status` (`accepted` | `unknown`), `error` (optional).

### `peer_message_delivery` daemon → agent

Delivers an accepted message to the recipient. Fields: `message_id`, `from_handle` (or `null`), `from_relation` (`self` | `parent` | `ancestor` | `child` | `descendant` | `peer` | `unknown`), `from_product_role` (optional display label, e.g. `copilot`), `message`, `interrupt`.

Recipients render the sender label preferring product role, then structural relation, then a neutral label (e.g. `Message from <handle> (copilot):`). The handle is the only routable identity; role/relation labels are display-only.

### `peer_message_delivery_ack` agent → daemon

Recipient-side acknowledgement. Fields: `message_id`, `status` (`queued` when the recipient queued it, `failed` when it could not), `error` (optional).

### `message_status` client → daemon

Delivery lifecycle status for a stored peer message. Fields: `request_id` (correlation), `message_id`, `wait_until_delivery` (optional; when true, the daemon may wait for a terminal state or timeout), `timeout_s` (optional).

### `message_status_result` daemon → client

Lifecycle status only; no recipient answer or response fields. Fields: `request_id` (echo), `message_id`, `status` (`accepted` | `sent` | `queued` | `failed` | `unavailable` | `unknown`), `error` (optional), and nullable `created_at` / `sent_at` / `queued_at` / `failed_at` timestamps.

Terminal delivery states are `queued`, `failed`, `unavailable`, and `unknown`; `accepted` and `sent` are non-terminal. LLM-facing tools may render `queued` as `queued in recipient session` while preserving the protocol value.

### `cancel` client → daemon

Requests cancellation of an agent's current run. Fields: `request_id`, `target_handle`.

Authorization is subtree-only: the requester must have dispatched the target directly or transitively. Unlike `peer_message` and fork-ask, a known public handle does **not** authorize cancellation. A successful cancel recurses through the target's dispatch subtree: the current run of the target and each descendant is marked `failed` with `error: "cancelled"`, each tracked process group is terminated, and waiters are woken, so descendants stop immediately instead of waiting out their own disconnect grace.

### `cancel_ack` daemon → client

Fields: `request_id` (echo), `status`, `error` (optional). `status` is `cancelled` (at least one run in the subtree was cancelled), `not_found`, `not_authorized` (outside the requester's dispatch subtree), or `already_terminal`.

### `GET /runs/summary`

Compact rows for the in-Pi active-agent widget under the requested root session. Query: `root_id` (required, private root session id scoping the read), `limit` (optional, default `5`, clamped to 0–50).

The response contains only an `agents` array, ordered by current-run/agent recency. Rows carry `agent_handle`, `agent_type`, `session_name`, `status`, `created_at`/`started_at` (elapsed rendering), and `task` (`null` or a compact `{goal, current_task: {label} | null}` projection). Rows exclude private ids, counts, root liveness, models, roles, results, errors, exit codes, end times, skills, activity, task plans, descriptions, specs, prompts, env, cwd, report tokens, and message bodies.

### `GET /dashboard/snapshot`

The browser-safe global session read model. Every live structural root (`parent_id IS NULL`, `depth = 0`, `role = agent`) is always selected, regardless of age, plus a bounded prefix of disconnected roots seen within 24 hours. Copilot classification takes precedence, then durable workstream attachment, then Root. Agent-free roots remain visible.

Query: `recent_root_limit` (optional, default `5`, validated `1`–`50` at both HTTP edges); `selected_root_handle` (optional; pins one eligible disconnected root outside the prefix; cannot recover a root older than 24 hours).

The browser grows the limit by five through an explicit loader. The response echoes `recent_root_limit` and `recent_root_limit_max` (`50`); `roots_truncated` reports whether eligible disconnected roots remain omitted. Live roots do not consume prefix slots, so the response may exceed the requested limit. Non-selected disconnected roots may rotate as newer sessions enter the prefix.

Roots carry only public/session facets: `root_handle`, kind, session name, model/mode, repo/worktree/branch, live/timestamps, current task, up to 10 goal stages × 20 tasks, agent count/truncation, and up to 100 flat descendant rows. Descendants use `agent_handle`, `parent_handle`, computed depth, type/name/model/status/timestamps, and bounded task/activity/skill/result/error projections with explicit truncation. Ask answerers and their subtrees are hidden; activity excludes thinking. Never included: private root/agent/run IDs, cwd/session files, specs/prompts/env/report tokens, raw event/tool payloads, user/system/developer messages, hidden thinking, full result/error bodies.

One snapshot projection task runs at a time: a concurrent follower receives `429` with `Retry-After: 1`, cancellation does not release ownership before the worker finishes, and the browser keeps cached data while retrying; transport failures remain `503`.

### `GET /dashboard/messages`

Accepts a structural `root_handle` plus descendant `agent_handle` (both path-safe public handles). The lookup is cycle-safe, subtree-scoped, rejects ask subtrees, and reads only the selected agent's current run. It returns at most three newest `assistant_output` messages in chronological order; each text is ANSI/control stripped, capped at 4,000 characters, and reports whether it was truncated. Terminal result bodies and peer/user/system/developer messages are excluded.

These two UDS endpoints are not generic browser APIs: the TCP app maps only `/api/snapshot` and `/api/messages` to them after browser authentication and repeats public-handle validation at the edge.

### `create_workstream` client → daemon

Creates a new workstream in the daemon's SQLite store (durable, repo-neutral coordination state; worktrees not persisted, git remains the source of truth, `copilot/<slug>` encodes the slug).

- `request_id`: correlation id for the immediate acknowledgement.
- `workstream_id`: internal `ws_<uuid>` minted by the extension.
- `slug`: globally-unique three-word readable id (extension generates collision-free; daemon enforces uniqueness).
- `label`: human-readable label.
- `brief`: brief injected into `pi --workstream` sessions.
- `source_dossier_path`: Logseq dossier page the workstream points to (one dossier may have many workstreams).
- `constraints`: optional constraints.
- `source_repo_page_path`: optional repository cockpit/page path.

### `create_workstream_ack` daemon → client

Fields: `request_id` (echo), `status` (`created` | `slug_conflict`), `workstream_id` and `slug` (daemon-confirmed, or `null` on conflict), `error` (optional).

### `attach_workstream_agent` client → daemon

Attaches the requester's own session as a workstream agent (additive, concurrent, never overwriting). Fields: `request_id`, `workstream` (slug or id), `repo` (`<org>/<name>`; "which repos touched" derives from agent rows), `worktree_label`, `status` (optional, default `attached`; `attached` | `failed`), `error` (optional).

### `attach_workstream_agent_ack` daemon → client

Fields: `request_id` (echo), `status` (`attached` | `not_found`), `error` (optional).

### `update_workstream` client → daemon

Status update (open ↔ closed). Fields: `request_id`, `workstream` (slug or id), `status` (`open` | `closed`).

### `update_workstream_ack` daemon → client

Fields: `request_id` (echo), `status` (`updated` | `not_found` | `invalid_status`), `error` (optional).

### `revise_workstream` client → daemon

In-place content revision: bumps `version`, snapshots the new content into `workstream_versions`, retains the prior version. Identity (`id`/`slug`), dossier pointer, worktree, and attached agents are unchanged; status is not touched (use `update_workstream`). The client sends the full resolved content (unspecified fields carried forward from the current version). Fields: `request_id`, `workstream` (slug or id), `label`, `brief`, `constraints` (optional).

### `revise_workstream_ack` daemon → client

Fields: `request_id` (echo), `status` (`revised` | `not_found` | `error`), `version` (post-revision number, or `null`), `error` (optional).

### `error` daemon → client

Reports protocol/parse errors; closes the WebSocket for fatal frame errors. Codes: `protocol_version`, `invalid_frame`, `invalid_register`, `duplicate_node_connection`, `duplicate_agent_handle`, `unsupported_frame`.

## Manual smoke shape

1. Connect to `/ws` over the UDS.
2. Send `register` with `v: 28`.
3. Send `dispatch` with private `run_id` / `agent_id` and public `agent_handle`.
4. Use the `agent_handle` with `wait` (carrying a `request_id` the result echoes), or discover agents through `list_agents`.
5. Answer every daemon `ping` with a same-nonce `pong`. An unanswered incumbent probe releases the node id to the next registration.
