# workstreams

A standalone feature domain: durable, repo-neutral internal coordination state for copilot-staged work, built on the agent-dispatch primitive (`#core/swarm`). A workstream is persisted in the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams` and `workstream_agents`, beside `agents`/`runs`).

Identity: each workstream has an internal `ws_<uuid>` id and a globally-unique three-word readable `slug`. Worktrees are NOT persisted — git remains the source of truth; the `copilot/<slug>` worktree name encodes the slug. The dossier (Logseq work page, `work__<org>__<repo>__<slug>`) stays the user-facing durable record; the workstream points to it via `source_dossier_path`. One dossier may have many workstreams.

The domain (`pi/workstreams/`) consumes the workstream client methods and observability views from `#core/swarm/agents/*`; only `index.ts`'s depth-gating imports `resolveAgentDepthState` from the primitive.

## Tools

The record and its execution staging are decoupled: `create`/`edit` manage the durable daemon record; `launch` provisions the worktree + pane.

- **`create_workstream`** — creates a durable workstream record in the daemon from a dossier-backed brief (label, brief, optional constraints). Returns its internal `ws_<uuid>` id and readable three-word slug. Record-only: no worktree, no Herdr pane, no agent.
- **`edit_workstream`** — revises an existing workstream's content (any of label, brief, constraints) **in place, bumping its version and keeping the old version**. Identity (id/slug), dossier pointer, worktree, and attached agents are unchanged; unspecified fields carry forward from the current version. Record-only.
- **`launch_workstream`** — stages execution for an **existing** workstream (resolved by id/slug): provisions its `copilot/<slug>` worktree (idempotent) and best-effort opens a Herdr pane on it. Carries the workstream into whatever repo the session is in. Returns transient setup/herdr status + `next_step`. Does not create a record and does not start an agent.
- **`list_workstreams`** — repo-neutral listing from the daemon. Filters by `repo`, `dossierPath`, `query` (slug/label substring), and `status` (`open`/`closed`). A single-identifier lookup (query only) returns the workstream detail with its joined agent rows and version history.
- **`set_workstream_status`** — sets a workstream's status to `open` or `closed`.

## Content versioning

A workstream's content (`label`/`brief`/`constraints`) is versioned. `create_workstream` writes version 1; each `edit_workstream` bumps the version, snapshots the new content into the daemon's `workstream_versions` table, and retains every prior version (surfaced in the `list_workstreams` detail as `versions`). Identity and the dossier pointer stay stable across revisions, so a running agent is never stranded — the revised brief takes effect the next time an agent runs `pi --workstream`.

## `pi --workstream` startup flag

`pi --workstream` is a boolean flag. Bare `--workstream` infers the workstream from the current `copilot/<slug>` worktree label; `--workstream=<slug|id>` resolves explicitly (the value is recovered from argv). On start it attaches the session as an additive workstream agent (appends a `workstream_agents` row — concurrent, never overwrites) and injects the brief. "Which repos touched" derives from agent rows.

## Multi-agent and cross-repo carry

A workstream can have several agent sessions over time or concurrently — every `pi --workstream` session appends an agent row. A workstream can be carried into a different repo by passing its id/slug to `launch_workstream`, enabling cross-repo coordination without a duplicate workstream.

## Protocol

Workstream management uses four WS frame pairs (`create_workstream`/`attach_workstream_agent`/`update_workstream`/`revise_workstream` + acks, protocol v22) and two HTTP GET endpoints (`/workstreams` filtered list, `/workstreams/{id_or_slug}` workstream + joined agents + version history). See [`core/hub/protocol/PROTOCOL.md`](../core/hub/protocol/PROTOCOL.md).
