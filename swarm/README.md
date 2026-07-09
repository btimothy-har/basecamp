# swarm

This context owns Basecamp's async-agent domain: the TypeScript runtime (`swarm/ts`: public daemon tools, launch policy, daemon client/reporting code, `/code-review`, workstreams), the Python daemon (`swarm/py` → `basecamp.swarm`), the wire-protocol contract (`swarm/protocol/`), and the `agents` skill (`swarm/skills/`).

The context's default register (composed by `extension.ts`) wires the agent catalog provider, the daemon client, the `/code-review` command, and the workstream tools/startup.

## Code review

`/code-review` runs an independent, third-party review of the current branch. The command owns orchestration end-to-end — the primary agent triggers it and receives the result, but never authors or synthesizes it.

Flow:

1. Resolve scope in the active worktree: the current branch vs its base (`origin/HEAD`, falling back to `main`; an optional argument overrides the base). The review covers every change since the branch's merge-base with the base — committed, staged, unstaged, and untracked — so uncommitted work is included.
2. Dispatch six independent reviewer agents (`security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`) via the daemon client with a fixed, scope-only brief — they read the diff directly, with no author narration.
3. Transpose each reviewer's prose report into a canonical `Finding` schema with a per-report LLM pass (the `fast` model, a forced `report_findings` tool) — faithful extraction only, no cross-report consolidation.
4. Merge findings and compute a verdict with deterministic code (no LLM synthesis): any critical → Request Changes; ≥3 high → Request Changes; 1–2 high → Comment; only medium/low → Approve with notes; none → Approve. The review is fail-fast and all-or-nothing: if any reviewer fails to dispatch, complete, produce output, or transpose into structured findings, the entire review aborts with a notification naming the failing reviewer — no verdict and no partial result are produced.
5. When a UI is available, present an interactive per-finding reaction pane so the user can page through the findings and leave an optional free-text reaction on each before the agent engages (reactions seed the follow-up discussion; they are not accept/reject decisions).
6. Persist a JSON artifact to scratch — the structured findings plus the user's per-finding reactions; raw reviewer prose is not retained. Then inject a compact framing prompt carrying the verdict, counts, and a link to the artifact (the findings themselves are not dumped inline) so the primary agent reads the packet and triages as the reviewee.

The review module lives in `swarm/ts/agents/review/` (`findings`, `transpose`, `synthesis`, `orchestrate`, `format`, `command`, `annotate-pane`, `command-helpers`). It is manual only — there is no automatic or backgrounded firing. v1 reviews the current branch; PR and arbitrary-branch targets are a planned follow-up.

## Agent lifecycle

Dispatched agents can be stopped with the `cancel_agent` tool, which cancels an agent you dispatched and terminates its process (subtree-only: you cannot cancel agents outside your dispatch tree). Agents are also reaped automatically when their dispatcher session ends and does not reconnect within `BASECAMP_AGENT_DISCONNECT_GRACE_S` (default 3600s). See `swarm/protocol/PROTOCOL.md`.

## Workstreams

The workstream domain lives in `swarm/ts/workstreams/` and provides durable, repo-neutral internal coordination state for copilot-staged work. A workstream is persisted in the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams` and `workstream_agents`, beside `agents`/`runs`) — the former JSON launch-index is gone (clean break, no migration).

Identity: each workstream has an internal `ws_<uuid>` id and a globally-unique three-word readable `slug`. Worktrees are NOT persisted — git remains the source of truth; the `copilot/<slug>` worktree name encodes the slug. The dossier (Logseq work page, `work__<org>__<repo>__<slug>`) stays the user-facing durable record; the workstream points to it via `source_dossier_path`. One dossier may have many workstreams.

### Tools

- **`launch_workstream`** — creates a new workstream + `copilot/<slug>` worktree + Herdr pane from a dossier-backed brief, OR carries an existing workstream into the current repo when given `workstream_id` (an existing id/slug; reuses the worktree idempotently; no dedup). Returns id/slug + transient setup/herdr status. Does not start an agent.
- **`list_workstreams`** — repo-neutral listing from the daemon. Filters by `repo`, `dossierPath`, `query` (slug/label substring), and `status` (`open`/`closed`). A single-identifier lookup (query only) returns the workstream detail with its joined agent rows.
- **`set_workstream_status`** — sets a workstream's status to `open` or `closed`.

### `pi --workstream` startup flag

`pi --workstream` is a boolean flag. Bare `--workstream` infers the workstream from the current `copilot/<slug>` worktree label; `--workstream=<slug|id>` resolves explicitly (the value is recovered from argv). On start it attaches the session as an additive workstream agent (appends a `workstream_agents` row — concurrent, never overwrites) and injects the brief. "Which repos touched" derives from agent rows.

### Multi-agent and cross-repo carry

A workstream can have several agent sessions over time or concurrently — every `pi --workstream` session appends an agent row. A workstream can be carried into a different repo by passing its id/slug to `launch_workstream`, enabling cross-repo coordination without a duplicate workstream.

### Protocol

Workstream management uses three WS frame pairs (`create_workstream`/`attach_workstream_agent`/`update_workstream` + acks, protocol v19) and two HTTP GET endpoints (`/workstreams` filtered list, `/workstreams/{id_or_slug}` workstream + joined agents). See `swarm/protocol/PROTOCOL.md`.

