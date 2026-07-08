# pi-swarm daemon runtime

This package owns the Python async-agent daemon runtime.

It contains the FastAPI application, Unix-domain-socket server runner, protocol frame models, in-memory runtime registry, and SQLite persistence used by `basecamp swarm daemon`.

## Run lifecycle

Dispatched agents are spawned in their own process group so the daemon can tree-kill a run. Dispatched-run processes are cleaned up on dispatcher disconnect (after `BASECAMP_AGENT_DISCONNECT_GRACE_S`, default 3600s, unless the dispatcher reconnects), on explicit `cancel`, and on daemon startup (orphaned runs are reconciled to `failed` and their process groups best-effort killed). See `pi-swarm/protocol/PROTOCOL.md` for the frame- and status-level contract.

## Workstream persistence

Workstreams are durable, repo-neutral internal coordination state persisted in the daemon's SQLite database (`~/.pi/basecamp/swarm/daemon.db`), alongside the `agents` and `runs` tables. The former JSON launch-index is gone (clean break, no migration).

### Tables

- **`workstreams`** — one row per workstream. Columns: `id` (`ws_<uuid>`, primary key), `slug` (globally-unique three-word readable id), `label`, `brief`, `constraints`, `source_dossier_path` (pointer to the Logseq dossier work page), `source_repo_page_path`, `status` (`open` or `closed`, default `open`), `created_at`, `updated_at`.
- **`workstream_agents`** — additive agent rows. Every `pi --workstream` session appends a row (never overwrites). Columns: `workstream_id` and `agent_id` (composite primary key; `agent_id` references `agents.id`), `repo` (`<org>/<name>`), `worktree_label`, `status`, `error`, `joined_at`. "Which repos touched" derives from these rows.

### HTTP endpoints

- `GET /workstreams` — filtered list. Query params: `status` (`open`/`closed`), `repo`, `dossier_path`, `query` (slug/label substring). Returns `{"workstreams": [...]}`.
- `GET /workstreams/{id_or_slug}` — single workstream with its joined agent rows. Returns 404 when absent.

### WS frames

Workstream writes use three request/ack frame pairs (protocol v19): `create_workstream`/`create_workstream_ack`, `attach_workstream_agent`/`attach_workstream_agent_ack`, and `update_workstream`/`update_workstream_ack`. See `pi-swarm/protocol/PROTOCOL.md`.
