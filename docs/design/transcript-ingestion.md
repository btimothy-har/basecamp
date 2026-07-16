# Transcript Ingestion — Design & Rationale

**Status:** BUILT (2026-07) · **Scope:** how Claude Code session *transcript content* lands in the hub daemon · **Builds on:** [claude-code-compatibility](./claude-code-compatibility.md) (why the hub is kept, slimmed) · **Delivery:** [`claude/README.md`](../../claude/README.md) · **Depends on:** the sessions + episodes schema (PR #274)

The hub daemon already records session *metadata* — a durable `sessions` row (identity) and `episodes` (liveness), plus the transcript file *path* captured at SessionStart. This increment ingests the transcript *content*: the raw conversation DAG of the **main thread and every subagent sidecar**, stored verbatim and uuid-keyed, so the daemon holds the data a future analysis/memory layer would need. It is **ingest-and-store only** — no analysis, no recall (see §6).

---

## 1. The inversion: the daemon reads the file

Pi's hub received a session's thread as a **WebSocket push** — the session streamed its turns to the daemon. Claude Code has no such channel, and it doesn't need one: the transcript is an **append-only JSONL file on disk** whose path the daemon already stored at SessionStart (`~/.claude/projects/<slug(cwd)>/<session_id>.jsonl`). So ingest inverts — the **daemon reads the file itself**, and the hook is a thin *trigger* carrying no payload of substance.

This makes the hook cheap (fire-and-forget, fail-open) and the daemon the single reader, which matters because the same file is re-read on every trigger (§2).

## 2. Triggers: SessionEnd + PreCompact + SubagentStop, coarse and idempotent

Three hooks fire an ingest. Each selects an ingest *mode* by which fields it sends (`hub/claude/ingest.py`); correctness never depends on the timeliness triggers, because the SessionEnd backstop needs only `session_id`:

- **SessionEnd** — the guaranteed last-chance capture, and the sidecar backstop. Fires on every engagement close (`logout`, `clear`, `resume`, …). The payload carries **no** `transcript_path`, so the daemon falls back to the stored path; it also sets `sweep_sidecars`, so the daemon ingests the main file **and** walks the whole `subagents/` tree, storing every sidecar not already captured. At session end every subagent is complete, so a full sweep is safe.
- **PreCompact** — cheap insurance before Claude Code compacts. Compaction is **append-only and non-destructive** (§3), so SessionEnd alone would still capture every pre-compaction turn; PreCompact only narrows the window in which a crash between compaction and SessionEnd could lose them. Its payload *does* carry `transcript_path`, which overrides the stored path. It ingests the **main file only** — a peer sidecar may be mid-write, and the SessionEnd sweep will catch it once done.
- **SubagentStop** — a timeliness optimization, one per subagent completion. Its payload carries `agent_transcript_path` (the just-finished sidecar) and `agent_id`, so the daemon ingests **that one sidecar** immediately. Because the subagent has finished, its file is complete — no partial-read risk from in-flight peers. If a `agent_transcript_path` is ever absent, the handler no-ops and SessionEnd still captures it.

Verified against the shipped `claude` 2.1.204 binary: `SubagentStop`, `agent_transcript_path`, `agent_id`, and `agent_type` are all real payload string literals.

There is **no byte-offset cursor**. Each trigger reads whole files and bulk `INSERT OR IGNORE`s every node; nodes already stored collide on their `uuid` primary key and are silently ignored. The full sweep additionally skips a sidecar whose `source_agent_id` is already stored (`has_agent_nodes`), so a subagent captured early by SubagentStop is never re-parsed. Coarse full-file re-reads are simple and self-healing, at the cost of re-parsing — acceptable at session-lifecycle cadence. If re-parse cost ever bites, an offset cursor is a compatible later optimization.

## 3. Transcript format facts that shape the schema

Empirically validated on real transcripts (`claude` 2.1.204 / 2.1.210):

- **DAG nodes carry a `uuid` (+ usually `parentUuid`):** `user` | `assistant` | `system` | `attachment`. Tool calls/results live *inside* an assistant/user line's `message.content` blocks, not as separate lines. **UI/state markers carry no `uuid`** (`mode`, `permission-mode`, `ai-title`, `last-prompt`, `queue-operation`, `file-history-*`) — transient editor state, skipped. The ingest rule is exactly *"has a `uuid` ⇒ store it."*
- **Fork copies nodes verbatim.** A forked session gets a new `session_id` and a **self-contained copy of the parent's transcript** — parent `uuid`s preserved, `sessionId` rewritten per line, no fork marker. So forks are undetectable from one file but dedup themselves at ingest via `uuid` overlap.
- **Compaction is append-only.** It appends a `system` / `compact_boundary` node (with `logicalParentUuid`, and `parentUuid: null` — it **re-roots** the physical chain) then a `user` summary node. A compacted session's DAG therefore has *multiple* `parentUuid: null` roots (original + one per compaction); `logicalParentUuid` bridges each boundary to the pre-compaction leaf. (Validated: N compaction boundaries ⇒ N+1 roots ⇒ N logical bridges.)
- **Subagents write a separate sidecar** (`…/<session_id>/subagents/agent-<id>.jsonl`, all `isSidechain: true`, own uuid space, tagged with the parent's `sessionId`); workflow fan-out nests deeper (`subagents/workflows/wf_*/agent-*.jsonl` plus a `journal.jsonl` the parser skips, having no `uuid`). Main files carry `isSidechain: 0`. **The main file keeps zero subagent content** — only the final tool_result string — so the sidecars are the *sole* record of a subagent's work. Combined with Claude Code's 30-day sweep of `~/.claude/projects/`, deferring sidecar ingestion would risk permanent loss, so it is ingested now (§2), not deferred.
- **Parent linkage is out-of-band.** A sidecar never links into the main DAG via `parentUuid` (zero cross-file edges), so the tie to the spawning call is captured explicitly: the sidecar's sibling `agent-<id>.meta.json` carries a `toolUseId` that matches the `id` of the `Task`/`Agent` tool_use block inside a main-thread assistant node (empirically verified). Workflow fan-out agents are spawned by the orchestrator, not a main-thread tool call, so they have **no** `toolUseId`.

**Consequence:** a thread is reconstructed by walking `parent_uuid` (bridged by `logical_parent_uuid`), **not** by filtering `session_id` — a node shared with a fork keeps only its first ingester's session label. A subagent's parent is recovered instead through its `source_tool_use_id` (§4).

## 4. Schema: `transcript_nodes`

One verbatim row per node, keyed by the node's own `uuid`. Additive, create-if-not-exists DDL (the store has no migration mechanism — stay additive, never `ALTER`).

| Column | Purpose |
|---|---|
| `uuid` (PK) | node identity; makes re-ingest and fork copies idempotent |
| `session_id` | the ingesting file's session (a *label*, first-writer-wins — not a reconstruction key) |
| `parent_uuid` | in-file DAG edge (`NULL` on each root) |
| `logical_parent_uuid` | compaction bridge across a `compact_boundary` |
| `episode_id` | best-effort: the engagement live when the node was first seen |
| `type` | `user` / `assistant` / `system` / `attachment` |
| `is_sidechain` | `0`/`1`; `0` for main-thread nodes, `1` for sidecar (subagent) nodes, stored faithfully |
| `source_agent_id` | subagent nodes only: the sidecar's agent id (`agent-<id>`), grouping one subagent's nodes; `NULL` on the main thread. Also the `has_agent_nodes` skip key |
| `source_tool_use_id` | subagent nodes only: the sidecar's `meta.json` `toolUseId` → the parent `Task`/`Agent` tool_use block in the main thread. `NULL` on the main thread and for orchestrator-spawned workflow agents |
| `timestamp` | native ISO timestamp |
| `seq` | physical line index at first ingest (order hint; reconstruction still walks the DAG) |
| `line_json` | the verbatim JSONL line — the opaque source of truth |
| `first_seen_at` | when this daemon first stored the node |

Both `source_*` columns are batch-level: stamped on every node of one sidecar file, `NULL` for the main file. Because the store has **no `ALTER`-based migration** (tables are created once, fully-formed, and never altered), `transcript_nodes` is introduced **with these columns from the start** — this feature ships as a single commit, so no reachable revision ever creates a narrower version of the table that a persistent `~/.pi/basecamp/claude/daemon.db` could then diverge from. Adding a column in a follow-up would silently break ingestion against an already-created table (`CREATE TABLE IF NOT EXISTS` is a no-op, and `record_nodes` would reference a missing column); the single-commit introduction is what keeps that from happening.

Indexes: `session_id`, `parent_uuid`, `source_tool_use_id` (parent → children lookup). `INSERT OR IGNORE` + the `uuid` PK is the whole idempotency and fork-dedup story.

## 5. Flow and layering

```
SessionEnd / PreCompact / SubagentStop hook  →  client.ingest_transcript (best-effort, no-spawn)
   →  POST /sessions/{id}/ingest  (resolve path + live episode synchronously)
   →  IngestScheduler.schedule    (fire-and-forget background task)
   →  ingest_session: mode-select main file and/or sidecar(s)
        →  parse_transcript(file)  →  store.record_nodes (INSERT OR IGNORE)
```

- **`hub/claude/transcript.py`** — pure JSONL → node-dict parser (skips uuid-less markers, lifts the routed columns, lenient on blank/malformed lines). Decodes with `errors="replace"`, so a tail truncated mid-multibyte character — the exact mid-write state PreCompact/SessionEnd can read — degrades to a skipped bad line (`UnicodeDecodeError` is a `ValueError`, not the `OSError` the caller guards, and would otherwise abort the whole parse and discard the good prefix).
- **`hub/claude/sidecars.py`** — subagent sidecar discovery: `discover_sidecars` (recursive `rglob` over `subagents/`, direct + workflow-nested) and `sidecar_for` (one path → `Sidecar` with `agent_id` from the filename and `tool_use_id` from the sibling `meta.json`).
- **`hub/claude/store/transcripts.py`** — `TranscriptsMixin`: schema + `record_nodes` (bulk `INSERT OR IGNORE`, stamps the two `source_*` linkage keys, returns new-node count) + `count_transcript_nodes` + `has_agent_nodes` (the sweep skip primitive).
- **`hub/claude/ingest.py`** — `ingest_session` (pure, testable; three modes: targeted sidecar / main+sweep / main-only) + `IngestScheduler` (backgrounds the slow parse so the hook's short-timeout POST returns immediately and survives client disconnect).
- **`hub/claude/routes.py`** — `POST /sessions/{id}/ingest`. Resolves `transcript_path` (body → stored) and `episode_id` (the live episode) **synchronously**, then schedules; returns `{scheduled: bool}`. A SubagentStop schedules on its `agent_transcript_path` alone, even with no stored main path.
- **`hub/claude/contract.py`** — `TranscriptIngestBody` (`transcript_path` / `sweep_sidecars` / `agent_transcript_path` / `reason`); `CLAUDE_PROTOCOL_VERSION` bumped **2 → 3**, so a running v2 daemon (which would accept the POST but silently ignore the new mode fields, never storing subagent transcripts) is health-gated out and respawned.
- **`hooks/session.py`** — `handle_pre_compact` (main only, payload path), `handle_session_end` (ingests with `sweep_sidecars=True` **before closing the episode** so tail nodes are tagged with the ending engagement), and `handle_subagent_stop` (targets the payload's `agent_transcript_path`).
- **`app.py`** — a shutdown `lifespan` drains the ingest scheduler (bounded, 3s) so a detached SessionEnd ingest completes before the process exits; the respawn path's stop timeout (`client/process.py`, 5s) is held above that window so a graceful drain beats SIGKILL.

Concurrency: ingest writes on background threads (parallel `SubagentStop` sweeps can run several at once) while lifecycle reads/writes continue on the request path. `_init_db` enables **`journal_mode=WAL`** so readers never block behind the single writer — otherwise a background ingest write could stall the `/ingest` route's synchronous reads (`get_transcript_path`/`current_episode_id`) until `busy_timeout` elapsed and they errored, and a 500 there would be silently read as "not scheduled" by the fail-open client, dropping the guaranteed SessionEnd ingest. `_connect` still sets `PRAGMA busy_timeout` (per-connection) so a contended *write* waits rather than erroring, and the route wraps its reads in a `try/except sqlite3.OperationalError` that degrades to an explicit `{scheduled: false}` instead of an unhandled 500. Under WAL SQLite is still single-writer, so the co-firing `/end` write (`close_episode`, which the SessionEnd hook calls immediately after the sweep ingest) can itself wait behind the in-flight ingest write; it is guarded the same way, degrading to `{ended: false, reason: "store busy"}` rather than a 500 that would silently lose the episode's `end_reason`. `_ingest_file` likewise degrades on a per-file parse/decode error (not just a missing file) so one corrupt file can never abort a SessionEnd sweep mid-loop. `INSERT OR IGNORE` keeps concurrent ingests safe.

## 6. Non-goals (deferred, by decision)

Kept deliberately narrow — *ship the raw data, reduce late.* Explicitly **not** in this increment:

- **No analysis.** No analyzer, no `analysis` table, no LLM pass. (Pi's warm-analyzer half is dropped for Claude; only the "store raw" principle survives.)
- **No consumer surface.** No companion UI, no `/analysis` endpoint, no recall/embeddings.
- **No parent-linkage resolution surface.** The `source_tool_use_id` key is *stored*, but nothing yet joins a subagent's nodes back to their spawning main-thread node — that reconstruction is a consumer concern.
- **No retention/pruning.** Insert-only; growth management is a later concern.

These are storage's downstream consumers; storing faithfully now — main thread **and** sidecars, with the linkage key captured — is what makes them buildable later without a reingest. (Sidecar ingestion itself was a deferred non-goal in the first draft; it was pulled forward once the 30-day on-disk sweep showed deferral risked permanent loss — see §3.)
