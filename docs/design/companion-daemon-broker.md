# Companion Daemon Broker — Design

**Status:** PROPOSED (clean-sheet redesign of the companion data + analysis path) · **Scope:** Supersedes the file-based producer/consumer seam and per-turn subprocess analyzer of `repo-rearchitecture.md` §6.4; the Textual UI, pane adapters (herdr/tmux), and Herdr metadata are retained · **Depends on:** the swarm daemon (`async-agents.md`)

This document describes moving the companion off its file-mirror data plane and onto the swarm daemon as a single broker. The extension becomes a thin producer that ships the raw session thread to the daemon at the end of every turn; the daemon persists it verbatim and derives an analysis view on demand. The Python Textual UI stays; the data plane is designed bidirectional but ships read-only.

---

## 1. Problem statement

Today's companion is a Python Textual TUI that merges **five independently-produced channels** on a 1-second poll (see the architecture study for the full map):

- a per-session **snapshot file** and a `.live-<pid>.json` mirror (workspace, cwd, model, mode, title — plus `tasks`/`goal`/`progress`/`skills_used` fields that are written but never rendered),
- the **goal-cycle store** (`tasks/<sid>.json`), read cross-language for the actual task display,
- an **analysis sidecar** (`analysis/<sid>.json`) written by a cold `basecamp companion analyze` subprocess spawned on every `agent_end`,
- the **swarm daemon** over UDS HTTP for the async-agent view,
- **git**, shelled out synchronously on the UI thread each tick.

Three structural costs follow:

- **Schema drift.** The snapshot schema is hand-mirrored in TS and Python; the daemon wire shape is reimplemented a third time; the goal-cycle schema is mirrored from `tasks.ts`. Versions exist but nothing negotiates them.
- **A cold analyzer with a low ceiling.** Each turn spawns Python + PydanticAI from cold, runs a full LLM call under a 60s watchdog, fire-and-forget over a file, on its own hardcoded model (`anthropic:claude-sonnet-4-6`) outside `pi/core/model`. Worse, its input is `buildUserContext` ([user-context.ts:78](../../pi/core/session/user-context.ts)) — the **first 3 + last 3 user messages, capped at 8K chars, with every assistant message and tool result stripped**. The analyzer reasons about what the agent is doing from the user's prompts alone.
- **Redundancy and coupling.** Half the snapshot is write-only; the tasks file is read twice on two different keys; the session-id is sanitized on some paths and raw on others.

## 2. Goals and non-goals

### Goals

- **One contract, not five.** The companion reads from a single source — the daemon — over the daemon's existing, versioned, cross-tested frame protocol, retiring the snapshot and analysis files.
- **A faithful, durable thread record.** The daemon holds the full raw session thread, so analysis is reproducible and re-derivable, and its quality is bounded by the model, not by a lossy digest.
- **Keep the Textual UI.** The renderer (diff viewer, file tree, syntax, swarm tab) is retained; only its data source changes.
- **Warm, unified analysis.** Analysis runs warm in the long-lived daemon, not as a cold subprocess per turn.
- **Design for control, ship read-only.** The transport is chosen so a control return-path (capture, redirect, message-agent) can land later with no re-architecture; v1 is observation-only.

### Non-goals

- **No LLM pre-summarization in the ingest or storage path.** Pi's `generateBranchSummary` is not in the pipeline; the analyzer reads the (reduced) conversation directly. (Reserved only as a fallback if a thread exceeds the analyzer budget even after compaction.)
- **No control frames in v1.** The return-path is reserved, not built.
- **No whole-tree/fork retention.** The daemon stores the active branch (`getBranch`), not abandoned forks. (`getEntries()`/`getTree()` would be the source if this ever changes.)
- **No transformation on ingest.** The extension ships what Pi gives, unadjusted. All reduction is deferred to analysis time (§6).

## 3. Direction

The daemon is already started (`ensureDaemon`) and connected at every top-level `session_start` — `ensureAndConnectTopLevel` ([daemon/index.ts:180](../../pi/swarm/agents/daemon/index.ts)) — as the root `session` node. But the telemetry **reporter is wired only for spawned sub-agents**, not the primary session ([index.ts:232](../../pi/swarm/agents/daemon/index.ts)), which is precisely why the primary session's state has to leave through snapshot files. The daemon, its connection, and the frame protocol already exist; this design **extends that path**, it does not build a new one.

Two ideas anchor the design:

1. **The daemon stores nodes, not content; pi-format knowledge is confined to the analyzer.** `async-agents.md` makes "the daemon never parses pi formats" a foundational principle ([:29](async-agents.md), [:58](async-agents.md)) — the drift-elimination that justifies the whole cross-language design. We preserve it: the extension extracts each entry's **envelope** (`id`, `parentId`) so the daemon stores thread nodes keyed by id with **opaque `entry_json` content** it never inspects in its coordinator/router/store paths. The daemon learns the *shape* of a thread (a DAG of identified nodes) but not what's inside them. The only component that reads pi `SessionEntry` **content** is the **analysis-time reducer** (§6) — a leaf subsystem, versioned against the entry schema, not the daemon core. Envelope extraction lives extension-side; content stays opaque until the reducer.

2. **Ship raw, reduce late.** The extension does no *content* transformation — it only splits the branch into per-entry nodes, each serialized verbatim. The daemon persists nodes as-is (inserting only new ones). Reduction (compaction application + tool-noise stripping) happens only when the analyzer runs, so it can evolve without re-ingesting and the stored record stays maximally faithful.

## 4. The ingest path — ship at `agent_end` *(the core of this design)*

### 4.1 Producer

On `agent_end`, the extension calls `sessionManager.getBranch()` and ships the result to the daemon as a frame. That is the entire producer responsibility — no reduction, no schema mapping, no file writes.

```
on agent_end (top-level session only, agentDepth 0):
  nodes = ctx.sessionManager.getBranch().map(e =>       // raw SessionEntry[] → per-entry nodes
            { id: e.id, parent_id: e.parentId, entry_json: JSON.stringify(e) })
  send frame: thread_report {
    node_id, session_id, session_file,                  // getSessionId() + getSessionFile() (.jsonl path)
    leaf_id: getLeafId(), nodes,
  }
```

- Ships from `registerRawThreadReporter` ([raw-thread-reporter.ts](../../pi/swarm/agents/daemon/raw-thread-reporter.ts)), a top-level sibling of the sub-agent telemetry reporter, over the WebSocket the primary session already holds (which today registers but does not report).
- Sent over the WebSocket the primary session already holds. No new connection.
- Gated to `agentDepth === 0` and `hasUI` sessions, consistent with the current companion gating.

This deletes the current producer surface: the snapshot writer, the `.live-<pid>.json` mirror, and `analysis.ts`'s subprocess-spawn/watchdog logic all go away. The extension's remaining companion job is pane management (herdr/tmux) and Herdr metadata, which are unchanged.

### 4.2 What `getBranch()` returns (confirmed from source)

`getBranch(fromId?)` ([session-manager.js:854](../../node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.js)) is a pure ancestry walk — `leaf → root` via `parentId`, unshifted to root→leaf order, with no filtering or resolution:

- **All entry types, raw and unresolved.** `message`, `compaction`, `branch_summary`, `model_change`, `thinking_level_change`, `custom`, `custom_message`, `label`, `session_info` ([SessionEntry union, session-manager.d.ts:101](../../node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.d.ts)).
- **Compaction is a marker, and the pre-compaction entries remain.** A `CompactionEntry` (`{ summary, firstKeptEntryId, tokensBefore }`) sits inline; the entries it summarized are still present because the walk continues to root. The cut is applied only by `buildSessionContext`, never by `getBranch`. **The daemon therefore holds strictly more than the LLM ever saw** — full pre-compaction detail plus Pi's already-computed summary.
- **Active branch only.** The walk follows a single `parentId`, so the result is the path to the current leaf, not sibling/abandoned forks. `leaf_id` is recorded so a fork (a new leaf whose path diverges) is distinguishable across pushes.

Because tool results and calls live inside `message` entries (`AssistantMessage.content` includes `ToolCall`; `ToolResultMessage` carries `toolName`/`isError`/`content` — [pi-ai/types.d.ts:197](../../node_modules/@earendil-works/pi-ai/dist/types.d.ts)), the raw thread contains everything the reducer needs; nothing is discarded before the daemon.

### 4.3 Session identity: rewind vs fork

`owner_id` is the connection's authenticated node — for a top-level session, pi's `getSessionId()` — and it is tied to the session *file*, not the branch. The two pi operations that "go back" therefore behave differently:

- **Rewind** (`branch(fromId)` / `resetLeaf()` — edit an earlier message and continue) moves the leaf pointer within the same session file ([session-manager.d.ts:270](../../node_modules/@earendil-works/pi-coding-agent/dist/core/session-manager.d.ts)). Same `getSessionId()` → **same `owner_id`**; only the head's `leaf_id` moves, and the abandoned path is retained (§5). Nothing re-registers.
- **`/fork`** (`newSession({ parentSession })` / `createBranchedSession()`) mints a **new** session file and id. It fires `session_shutdown` (`teardownCurrent("fork", …)`) then `session_start` (`reason: "fork"`), so the daemon client closes and reconnects under the new id. Because `registerRawThreadReporter` resolves the *current* connection on every send (via `awaitDaemonConnection`, not a frozen promise), post-fork reports land under the new `owner_id` — a distinct head + tree. pi stamps the old→new lineage on the new session's header (`parentSessionPath`), so it stays recoverable without a branch table.

## 5. Storage — node by node, insert-only

pi already persists the full raw thread in its `.jsonl` transcript, so the daemon does not re-store the whole blob each turn. It holds each **immutable entry once**, keyed by `entry_id`, inserting only new nodes — dedup, querying, and cross-session joins are the value-add over the flat `.jsonl`. A per-session head row records the current `leaf_id` plus pi's `session_id` and `session_file` (the `.jsonl` path); the active branch is reconstructed by walking `parent_id` up from the head's `leaf_id` (a recursive CTE, the pattern the store already uses for agent trees).

```sql
-- per-session head: current leaf + pointers into pi's own session
CREATE TABLE raw_pi_thread (
  owner_id      TEXT PRIMARY KEY,   -- connection node id (authoritative; same space as agents.id)
  session_id    TEXT NOT NULL,      -- pi getSessionId()
  session_file  TEXT,               -- pi getSessionFile() — the .jsonl transcript path
  leaf_id       TEXT,               -- current leaf; reconstruction starts here
  latest_seq    INTEGER NOT NULL,   -- turn counter; the analyzer's freshness cursor
  updated_at    TEXT NOT NULL
);

-- one row per immutable entry; content opaque to the daemon
CREATE TABLE raw_pi_thread_node (
  owner_id        TEXT NOT NULL,
  entry_id        TEXT NOT NULL,
  parent_id       TEXT,             -- reconstruction walks this up from leaf_id
  first_seen_seq  INTEGER NOT NULL, -- the turn this node first appeared (delta cursor)
  entry_json      TEXT NOT NULL,    -- one serialized SessionEntry, verbatim + opaque
  PRIMARY KEY (owner_id, entry_id)
);

-- latest analyzer output per session — a persisted cache, not versioned history;
-- upserted each run, with provenance back to the thread turn it read
CREATE TABLE analysis (
  owner_id              TEXT PRIMARY KEY,
  based_on_thread_seq   INTEGER,            -- raw_pi_thread.latest_seq this analysis read
  model                 TEXT,
  sections_json         TEXT NOT NULL,      -- monitor / needs_capture / checkpoints
  updated_at            TEXT NOT NULL
);
```

The analysis is **latest-only** (one row per `owner_id`, upserted), not a versioned series. It is a pure derivative of the raw thread — the durable source of truth — so it is stored as a persisted cache: durable enough that a UI attaching cold (or right after a daemon restart) sees the last computed dashboard without paying to re-analyze, but not treated as precious history. Analysis-*over-time* is deliberately not kept here — how the agent's understanding evolves is already legible from the formal goal/task list, so a version history would be dead weight. (Going versioned later is a purely additive change: add a `seq`, stop upserting.)

Each `thread_report` bumps `latest_seq` on the head and does `INSERT … ON CONFLICT(owner_id, entry_id) DO NOTHING` per node — existing entries are no-ops (pi entries are immutable), new ones stamped `first_seen_seq = this turn`. Storage is O(distinct entries); the wire still re-sends the full branch each turn (a later delta optimization can send only new nodes). `first_seen_seq`/`latest_seq` give the analyzer both a delta ("nodes since seq N") and a freshness cursor (§6.1). Reconstruction (`get_raw_pi_thread_nodes`) returns the live branch (`.live`) by default; a rewind's abandoned branches are retained by the insert-only path and reconstructed *separately* into `.abandoned` only under an opt-in `include_abandoned` flag — the back-pocket "roads not taken", never the mainline analysis input. Retention rides on the async-agents TTL/cleanup item ([async-agents.md:510](async-agents.md)): a rolling window on `raw_pi_thread_node`, and the single `analysis` row falls away with its session.

## 6. Analysis-time reduction

Reduction is the **only** place pi `SessionEntry` *content* is read, and it happens when the analyzer runs, not on ingest. Given the reconstructed live branch (`get_raw_pi_thread_nodes(...).live` walks `parent_id` from the head's `leaf_id`, returning `entry_json` root→leaf), the daemon derives the analyzer's input by:

1. **Applying compaction (data-level, no LLM).** At a `CompactionEntry`, drop path entries before `firstKeptEntryId` and substitute the entry's `summary` string. The summary is already computed by Pi and embedded — the daemon applies a stored marker, it does not reimplement Pi's compaction algorithm.
2. **Reducing tool noise.** Walk the resolved messages:
   - `UserMessage` → keep text.
   - `AssistantMessage` → keep `TextContent` (and optionally `ThinkingContent`); render each `ToolCall` as `[tool: <name>]` (drop args).
   - `ToolResultMessage` → collapse to `[result: <toolName> <ok|error>]` + a short preview; drop the payload (the noise).

The result — the full conversational arc with the agent's reasoning and actions, tool dumps removed — is what the analyzer receives. This lifts the ceiling from "user prompts only" to "what the agent actually did."

The analyzer itself is a **warm service in the daemon** (Python/PydanticAI retained for richer, potentially cross-tree analysis), replacing the cold per-turn subprocess.

The analyzer is a **swappable seam**, not fixed logic. The scheduler, reducer, and store depend only on an `Analyzer` interface (`analyze(context, already_tracked, prior, model) → sections`); the concrete implementation is injected. v2 ships a **provisional** implementation that carries the existing prompt and `monitor`/`needs_capture`/`checkpoints` sections through PydanticAI, purely to make the pipeline run end-to-end. **Model policy is deliberately minimal in v2** — a single hardcoded `DEFAULT_ANALYSIS_MODEL` on the scheduler, not a config or alias-file lookup; choosing/configuring the model is part of the analyzer rework. Prompt, model policy, and output shape are all expected to change behind the seam without touching the reducer, scheduler, or `analysis` store.

### 6.1 The analyzer feeds off fresh turns

The daemon is a long-lived async process, so the scheduler is event-driven, not timed. The `thread_report` handler upserts `raw_pi_thread`, bumps an in-memory `latest_seq[node_id]`, and signals a per-node analyzer worker (an `asyncio.Event`/queue on the daemon loop). The worker runs only when `latest_seq > last_analyzed_seq` (the persisted `analysis` row's `based_on_thread_seq`, seeded on worker start so a daemon restart does not re-run stale turns) — it never runs on stale data and never polls. `seq` is the freshness cursor, so write-in-place storage is sufficient; "fresh" is a seq advance, not a distinct row. Consistent with "laggy is fine," the worker debounces/coalesces a burst of turns into one run and skips while a run is in flight — reactive to freshness, not obligated to be instant.

Two senses of "fresh" are kept distinct:

- **Trigger** — *run* when new turns land (the mechanism above). This is settled.
- **Input** — *what the LLM reads*. The input stays the full reduced, compaction-bounded thread plus the prior `analysis` row, because the "evolve the dashboard" model reconsiders the whole bounded thread rather than only appending; incrementality of *understanding* comes from carrying the prior analysis, not from truncating the input. Incremental *input* (only new turns) is a later cost optimization that would inherit re-baseline handling on fork (`leaf_id` change) or a new compaction prefix.

## 7. The seam and transport phasing

- **Extension** shrinks to: ship `getBranch()` on `agent_end`; manage the pane; report Herdr metadata. No files, no analyzer trigger.
- **Daemon** gains: a `thread_report` frame handler; `raw_pi_thread` + `analysis`; the reducer; the warm analyzer (a swappable seam — see §6); a unified current-state projection (extend the existing `/runs/summary` projection in `store/summary.py`).
- **Textual UI** reads one source instead of five, and keeps its own git for the diff view (moved off the render thread — git is inherently local and should not be daemon-owned).

Transport phases with the read-only-first goal:

- **v1 — HTTP poll of the unified projection.** The daemon's `/ws` accepts only agent registrations today; adding a read-only observer is out of scope for v1. The UI keeps polling, but a single unified projection endpoint — five channels collapse to one schema, no drift. Ships read-only.
- **v2 — WS observer + control.** Add an observer role to `/ws` for pushed deltas; this same channel carries control frames (capture item → tracked state, message/redirect agent), reusing the daemon's existing router. This is the "design for control" half.

## 8. Deprecation — the clean break

This is a removal, not old-and-new in parallel: keeping the snapshot/analysis files as a fallback would preserve the drift and redundancy the redesign exists to remove. The daemon becomes the single source; a daemon-down session shows a "starting…" state, not a file fallback. Sequenced in Phase 4, after Phases 1–3 prove the new path — except the pane-launch interface change, forced in Phase 3 when the UI stops reading snapshots.

**Removed (deleted):**

| Component | Path | Replaced by |
|---|---|---|
| Snapshot writer + `.live` mirror | `pi/companion/snapshot/` | `thread_report` → `raw_pi_thread` (§4–5) |
| Per-turn analyzer subprocess | `pi/companion/analysis.ts` | daemon analyzer worker (§6) |
| Dashboard file source (mtime merge) | `src/basecamp/companion/source.py` | daemon projection (§7) |
| Goal-cycle file read | `src/basecamp/companion/cycles.py` | task state in the projection (daemon already reads the tasks log) |
| Snapshot file loader + paths | `src/basecamp/companion/snapshot.py` (loader) | projection payload |
| `companion analyze` CLI + `companion-analyze` alias | `src/basecamp/cli.py` | daemon service, not a CLI |
| `--snapshot` launch flag | `pi/companion/panes/command.ts` | `--session-id` (query the daemon) |
| On-disk `companion/snapshots/` + `companion/analysis/` | `~/.pi/basecamp/…` | dead — no writer or reader |
| `BASECAMP_COMPANION_MODEL` | env | daemon-side model policy (v2: hardcoded default; config in the analyzer rework) |
| Corresponding test suites | `tests/companion/test_*`, TS `snapshot`/`analysis` tests | new ingest/analyzer/projection tests |

**Relocated / rewired (not deleted):**

- `analysis/generate.py`, `analysis/model.py`, `llm.py` — the analyzer, sections model, and PydanticAI adapter **move into the daemon** (swarm) as the warm service; the prompt and section logic survive, but IO changes (reads `raw_pi_thread`, writes `analyses`, event-driven; no stdin envelope, no sidecar).
- `app.py::_refresh` + `poll.py` — rewired to read the single projection; the daemon-client half stays and expands.
- `herdr/metadata.ts` — **retained but decoupled**: `buildHerdrMetadata` currently reads a `CompanionSnapshot`; it must build its title/status directly from core state (workspace, agent-mode, session title, tasks reader) once the snapshot writer is gone.
- `snapshot.py::render_workspace_lines` — repurposed to render the workspace panel from the projection.

**Retained (unchanged):**

- `pi/companion/panes/`, `herdr/provider.ts`, `tmux/` — pane management (only the launch command's data arg changes).
- The Textual `ui/` widgets, `diff.py` + the local git driver (moved off the render thread).
- `buildUserContext` — **not** companion-only: `pi/core/ui/title.ts` uses it for session-title generation, so it stays; only the companion's use (in the removed `analysis.ts`) goes.

## 9. Tradeoffs and risks

- **Pi-format coupling, scoped to two shallow places.** The daemon stores per-node rows but reads pi *content* nowhere in its coordinator/router/store paths. The extension extracts each entry's envelope (`id`, `parentId`) — legitimate, since "translation stays in the extension" — and the analysis-time reducer (§6) is the only reader of entry content. Both are versioned against the entry schema: if pi's envelope changes, only the reporter's mapping shifts; if content changes, only the reducer. The daemon core tracks neither.
- **Wire cost.** `getBranch()` re-sends the full branch each turn — O(N²) over the session — even though the daemon now dedups it to O(distinct entries) on write. It is local UDS, so bandwidth is nearly free, but the per-turn frame grows on long sessions. The drop-in fix (already enabled by node keying): send only entries past the last `first_seen_seq` and let `INSERT … DO NOTHING` reconcile. Ship the full-send first.
- **Charter and SPOF.** This promotes the daemon from async-agent coordinator to observation broker for every primary session. It is already started/connected at every session start, so it is not a new dependency — but a daemon-down session degrades from "no swarm tab" to "no dashboard." Mitigate with explicit "daemon starting…" UI states.
- **Retention.** `raw_pi_thread_node` grows with distinct entries per session and needs a bounded window — and since abandoned branches are deliberately retained (the opt-in `include_abandoned` pull), pruning must be ancestry-aware/generous, not a naive `first_seen_seq` cutoff that could delete a live ancestor. Rides on the async-agents cleanup item.

## 10. Open questions

- The reducer's exact tool-preview budget and whether `ThinkingContent` is included.
- The analyzer debounce/coalesce window (the event-driven wake and skip-in-flight are settled in §6.1; the quiet-gap interval is not).
- Whether to move to incremental analyzer *input* (only new nodes) and its fork/compaction re-baseline rules.
- Retention window for `raw_pi_thread_node`.
- v2 observer transport (WS observer role vs SSE) and the control-frame schema.
