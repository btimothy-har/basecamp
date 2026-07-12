# workstreams

A standalone feature domain: durable, repo-neutral internal coordination state for copilot-staged work, built on the agent-dispatch primitive (`#core/swarm`). A workstream is persisted in the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams` and `workstream_agents`, beside `agents`/`runs`).

Identity: each workstream has an internal `ws_<uuid>` id and a globally-unique three-word readable `slug`. Worktrees are NOT persisted — git remains the source of truth; the `copilot/<slug>` worktree name encodes the slug. The dossier (Logseq work page, `work__<org>__<repo>__<slug>`) stays the user-facing durable record; the workstream points to it via `source_dossier_path`. One dossier may have many workstreams.

The domain (`pi/workstreams/`) consumes the workstream client methods and observability views from `#core/swarm/agents/*`; only `index.ts`'s depth-gating imports `resolveAgentDepthState` from the primitive.

## Tools

- **`launch_workstream`** — creates a new workstream + `copilot/<slug>` worktree + Herdr pane from a dossier-backed brief, OR carries an existing workstream into the current repo when given `workstream_id` (an existing id/slug; reuses the worktree idempotently; no dedup). Returns id/slug + transient setup/herdr status. Does not start an agent.
- **`list_workstreams`** — repo-neutral listing from the daemon. Filters by `repo`, `dossierPath`, `query` (slug/label substring), and `status` (`open`/`closed`). A single-identifier lookup (query only) returns the workstream detail with its joined agent rows.
- **`set_workstream_status`** — sets a workstream's status to `open` or `closed`.

## `pi --workstream` startup flag

`pi --workstream` is a boolean flag. Bare `--workstream` infers the workstream from the current `copilot/<slug>` worktree label; `--workstream=<slug|id>` resolves explicitly (the value is recovered from argv). On start it attaches the session as an additive workstream agent (appends a `workstream_agents` row — concurrent, never overwrites) and injects the brief. "Which repos touched" derives from agent rows.

## Multi-agent and cross-repo carry

A workstream can have several agent sessions over time or concurrently — every `pi --workstream` session appends an agent row. A workstream can be carried into a different repo by passing its id/slug to `launch_workstream`, enabling cross-repo coordination without a duplicate workstream.

## Protocol

Workstream management uses three WS frame pairs (`create_workstream`/`attach_workstream_agent`/`update_workstream` + acks, protocol v20) and two HTTP GET endpoints (`/workstreams` filtered list, `/workstreams/{id_or_slug}` workstream + joined agents). See [`core/hub/protocol/PROTOCOL.md`](../core/hub/protocol/PROTOCOL.md).
