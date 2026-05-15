# Memory Agent North Star

Status: proposed architecture and implementation roadmap. `pi-memory` has implemented Phase 4 raw transcript recall, Phase 5A deterministic transcript structure/fork provenance, and Phase 5B replaceable session interpretation over episode packets; Pi recall tool wiring remains deferred.

Related issue: [#123](https://github.com/btimothy-har/basecamp/issues/123)

## Context

`pi-observer` currently provides semantic recall over previous Pi coding sessions by ingesting transcript JSONL, extracting structured artifacts, storing those artifacts in SQLite, and indexing them in ChromaDB. That implementation proves the value of local session recall, but the next memory system should not be constrained by the current observer's lifecycle, schema, or package boundaries.

The north-star system is a clean cutover: a Python-first local memory service that continuously captures full Pi transcripts, derives evolving session understanding, promotes durable source-backed memory artifacts into an associative graph, and serves explainable recall through a thin Pi adapter.

The current observer is useful inspiration. It should not be treated as a compatibility target.

## One-sentence north star

Build a Python-first local memory service that continuously captures full Pi transcripts, derives replaceable session-level understanding, promotes durable source-backed memory artifacts into an associative graph, and serves explainable recall through a thin Pi adapter using SQLite as canonical storage and ChromaDB as a rebuildable semantic index.

## Clean cutover stance

This design intentionally replaces the current observer behavior rather than migrating or preserving historical observer stores.

The new system should not require compatibility with:

- the existing `~/.pi/observer` data directory;
- current observer SQLite schemas;
- current observer Chroma collections;
- current extraction artifact shapes;
- current CLI behavior;
- current Pi extension orchestration behavior.

No legacy migration should be added unless a future product decision explicitly changes that requirement. The clean cutover lets the new system optimize for the desired architecture instead of carrying forward accidental constraints.

## Goals

- Store full Pi transcripts locally as the canonical source of truth.
- Keep memory analysis, indexing, reconciliation, and hygiene in Python.
- Keep the Pi extension as a thin sensor and UI adapter.
- Run a local FastAPI service on a fixed localhost port.
- Have Pi start or reconnect to the service when a session launches.
- Ingest transcript observations continuously rather than only at shutdown.
- Maintain replaceable working session snapshots during active sessions.
- Promote durable memory only through reconciliation.
- Represent durable memory as typed, source-backed, revisable artifacts.
- Model relationships between artifacts, concepts, sessions, episodes, source spans, files, modules, goals, and preferences as a graph.
- Use SQLite as the canonical store for transcripts, sessions, jobs, artifacts, revisions, source spans, graph nodes, graph edges, statuses, and provenance.
- Use ChromaDB as a rebuildable vector index over SQLite-backed records.
- Use service-owned durable jobs for heavy work and hygiene.
- Return recall packets with provenance and explanation, not only vector snippets.

## Non-goals

- No historical observer data migration.
- No compatibility requirement for old observer schemas or Chroma collections.
- No cloud sync.
- No multi-user server model.
- No external graph server as an initial dependency.
- No treating embeddings as canonical memory.
- No heavy memory logic in the Pi extension.
- No FastAPI `BackgroundTasks` as the durable job system.
- No reliance on `session_shutdown` as the only finalization point.
- No historical observer compatibility work unless a future product decision explicitly requires it.

## Design principles

### Raw transcript is canonical

The full transcript is the durable record of what happened. Derived memory can be deleted, reprocessed, reindexed, reclassified, or superseded.

```text
raw transcript + source spans = source of truth
derived artifacts + graph = interpretation
```

### Derived memory is revisable

A memory artifact is not a permanent summary line. It is a typed, source-backed claim that can be refined, superseded, contradicted, retracted, archived, or reinforced.

### Continuous ingest, reconciled promotion

The system should ingest session data continuously, but should not append permanent artifacts on every analysis pass. Active sessions use replaceable working snapshots. Durable project memory is promoted through reconciliation.

### Pi is thin

Pi observes and renders. The Python service thinks.

```text
Pi = sensor + UI
Python service = memory brain
SQLite/Chroma = memory substrate
```

### One canonical store, rebuildable indexes

SQLite owns canonical memory, graph, jobs, sessions, transcripts, and provenance. ChromaDB owns vector indexes, but every Chroma entry must be reconstructable from SQLite.

### Graph is associative context, not magic truth

The graph helps find relevant neighborhoods and explain recall. It does not by itself decide supersession, correctness, or user intent.

## Current observer as inspiration

The existing observer already has useful ideas:

- it stores full raw transcript payloads;
- it uses SQLite for durable local data;
- it uses ChromaDB for semantic retrieval;
- it extracts summaries, decisions, constraints, knowledge, and actions;
- it exposes recall through Pi tooling.

The new design should carry forward those lessons while avoiding the constraints that make the current shape hard to evolve:

- fire-and-forget lifecycle orchestration from the Pi extension;
- analysis centered on shutdown instead of continuous durable ingest;
- artifact extraction without graph-informed reconciliation;
- no durable job system for recovery, retries, and hygiene;
- limited distinction between canonical transcript data and derived memory state;
- recall focused on indexed artifacts rather than explainable graph-backed memory packets.

## Target architecture

```text
Pi extension
  - starts/checks local memory service
  - observes session lifecycle
  - sends session metadata/transcript path
  - exposes recall/memory tool
  - renders recall packets

FastAPI memory service
  - validates local HTTP requests
  - records observations
  - enqueues work
  - exposes recall/status/job APIs

Worker/scheduler loop
  - ingests transcript deltas
  - segments episodes
  - updates session maps
  - extracts candidate memories
  - maps candidates to graph neighborhoods
  - reconciles candidates with durable memory
  - promotes artifacts
  - updates Chroma/FTS indexes
  - runs hygiene/catch-up

SQLite memory.db
  - canonical transcript/session/job/artifact/graph/provenance store

ChromaDB
  - rebuildable vector index over SQLite-backed memory
```

### Pi extension responsibilities

The Pi extension should remain small and operationally boring.

Responsibilities:

- check service health on session launch;
- start the local service if unavailable;
- send session observations, transcript path, repository metadata, and lifecycle events;
- expose recall and memory-status tools or commands;
- render recall results in a useful format;
- degrade gracefully if the service is unavailable.

Non-responsibilities:

- transcript parsing;
- LLM analysis;
- artifact extraction;
- graph reconciliation;
- Chroma indexing;
- durable storage;
- long-running background work.

### Python service responsibilities

The Python service owns the memory system.

Responsibilities:

- provide a local HTTP API;
- validate requests from the Pi adapter;
- maintain the canonical SQLite database;
- enqueue and execute durable jobs;
- parse transcript deltas;
- maintain rolling session snapshots;
- extract candidate memory artifacts;
- reconcile candidates against graph neighborhoods;
- promote durable memory artifacts;
- maintain derived indexes;
- serve explainable recall packets.

### Worker and scheduler responsibilities

Heavy work should not run inside request handlers. The service should run a worker/scheduler loop backed by SQLite jobs.

Responsibilities:

- claim queued jobs;
- retry failed jobs according to job policy;
- recover stale running jobs after restart;
- enqueue catch-up work for stale sessions;
- run periodic hygiene;
- keep ChromaDB and FTS projections aligned with SQLite.

The first implementation can run FastAPI and the worker in the same local process. If needed later, the service can split into separate `serve` and `worker` commands using the same SQLite job queue.

## Runtime lifecycle

The desired lifecycle is:

```text
raw transcript
  -> episodes
  -> session map
  -> candidate memories
  -> graph reconciliation
  -> promoted durable memory
  -> recall / resurfacing / maintenance
```

### 1. Service startup

Pi launch checks the local service:

```text
GET http://127.0.0.1:<fixed-port>/health
```

If unavailable, Pi starts the service:

```text
pi-memory serve --host 127.0.0.1 --port <fixed-port>
```

The exact command name remains open, but the behavior should be stable: one local service process, one fixed localhost port, and a guard against duplicate servers.

Startup sequence:

```text
start server
  -> initialize SQLite
  -> acquire service lock
  -> recover stale running jobs
  -> scan sessions needing ingest/finalization
  -> start worker loop
  -> start scheduler loop
```

### 2. Continuous observation

Pi sends lightweight observations during session activity:

```text
POST /v1/observe
```

Observation payloads should include enough information for the service to locate and interpret session transcript data:

```text
session_id
transcript_path
cwd
repo
worktree
branch
event_type
timestamp
```

The endpoint should return quickly. It can enqueue work, but heavy ingest and analysis should run through durable jobs.

### 3. Transcript ingest

The service tracks per-session transcript cursors.

```text
session_id
transcript_path
cursor_offset
last_observed_at
last_ingested_at
```

Ingest reads transcript deltas, stores raw events, advances the cursor, and remains idempotent. Duplicate observations should be harmless.

### 4. Deterministic transcript structure

Raw transcript entries are first normalized into source-backed activity units, then grouped into structural episodes. This layer is deterministic and rebuildable from canonical SQLite transcript rows.

Activity units include:

- user text;
- assistant text;
- assistant thinking;
- paired tool call/result receipts;
- pending tool calls;
- orphan tool results;
- compaction events;
- session events;
- custom events, including source-backed `branch_summary` events with bounded metadata.

Activity source origins are fork-aware: `local`, `inherited`, `mixed`, or `unknown`. Parent/child transcript linkage is provenance for interpretation and eligibility decisions; raw child transcript rows remain exact records of the child transcript file.

Episode boundaries are lifecycle boundaries, not size boundaries:

- transcript/session scope;
- compaction;
- large timestamp gap;
- EOF or current cursor.

Raw tool output remains in `transcript_entries.raw_line`. Episode manifests store bounded `activity_map_json` with included and omitted ranges, counts, receipts, and source-span references so later interpretation can fetch the raw spans when needed.

### 5. Rolling session interpretation

After deterministic structure exists, an interpretation job maintains a replaceable session interpretation over bounded episode packets.

```text
session_interpretation_snapshots
- session_id
- transcript_id
- analysis_run_id
- job_id
- status: completed | blocked | skipped_no_claim_sources
- blocked_reason
- analyzed_through_entry_id
- analyzed_through_byte_offset
- origin_counts_json
- claim_source_activity_count
- interpretation_json
- citations_json
- model_metadata_json
- prompt_version
- schema_version
```

Phase 5B parses parent and child sessions separately. Inherited child activity is context only; only `local` or `mixed` activity is eligible as a memory-claim source. If a child session records a parent transcript path that cannot be resolved, interpretation writes a blocked snapshot with `blocked_reason = parent_transcript_not_ingested`. If source origin is incomplete, it writes `blocked_reason = source_origin_incomplete`. If no claim-source activities exist, it writes `skipped_no_claim_sources` without calling the interpreter.

Each new completed, blocked, or skipped interpretation replaces the previous current interpretation for that session. This prevents cumulative analysis from creating permanent duplicate or stale artifacts. The interpretation stage consumes `EpisodePacket` read models built from deterministic activity units, episode manifests, and bounded raw source spans; it does not replace them and it does not promote durable memory.

`session_snapshot_shells` remains a non-destructive Phase 5A compatibility artifact for now, but it is no longer the active Phase 5B handoff model. Phase 5B computes readiness directly from transcript lineage, latest completed `analysis_runs`, and `activity_units.source_origin`; it builds interpretation packets from `episodes` and `episode_manifests` after readiness is known.

### 6. Candidate extraction

From a session snapshot, the service extracts candidate durable memories. Candidates are not durable memory yet.

Candidate shape:

```text
kind
title
statement
canonical_key
concepts
entities
files/modules
source_spans
confidence
durability
```

Candidate kinds:

- decision;
- constraint;
- knowledge;
- preference;
- pattern;
- open question;
- action.

### 7. Graph mapping

Candidates are attached to the memory graph.

Graph nodes may include:

- Artifact;
- ArtifactRevision;
- Concept;
- Session;
- Episode;
- SourceSpan;
- Project;
- Repo;
- Worktree;
- Branch;
- File;
- Module;
- Tool;
- Goal;
- Question;
- UserPreference.

Graph edges may include:

- about;
- mentions;
- derived_from;
- supported_by;
- refines;
- supersedes;
- contradicts;
- depends_on;
- motivated_by;
- applies_to;
- implements;
- touches;
- similar_to;
- used_in_recall.

Edges should carry provenance and confidence where useful:

```text
confidence
source_span_id
analysis_run_id
metadata_json
created_at
```

### 8. Reconciliation

Promotion is a reconciliation process. For each candidate, the service finds nearby existing memory by:

- same canonical key;
- shared concepts;
- same files/modules/entities;
- same decision or constraint topic;
- semantic similarity via ChromaDB;
- recently active related sessions.

Then it classifies the relationship:

- new;
- duplicate;
- refines;
- supersedes;
- contradicts;
- supports;
- related;
- unrelated.

Suggested mutation rules:

```text
new
  -> create active artifact

duplicate
  -> merge support/source evidence

refines
  -> create new revision or update current artifact

supersedes
  -> mark old artifact superseded; create active artifact

contradicts high confidence
  -> create artifact and add conflict edge

contradicts low confidence
  -> keep both visible; mark needs_review

related
  -> keep both; write relation edge
```

Semantic similarity alone must not auto-supersede.

### 9. Promotion

Promoted artifacts become durable project memory.

Artifact states:

- candidate;
- active;
- superseded;
- conflicting;
- retracted;
- archived;
- needs_review.

Artifacts are source-backed and revisable.

Example:

```text
Artifact A:
  Decision: Use batch-only session-end analysis.
  status: superseded

Artifact B:
  Decision: Use continuous ingest plus graph-informed promotion.
  status: active
  supersedes: Artifact A
```

### 10. Recall

Recall returns memory packets, not raw vector snippets.

A recall result should include:

- artifact;
- kind;
- status;
- statement;
- reason returned;
- related concepts;
- source spans;
- relationship context;
- supersession or conflict context.

Example:

```text
Decision: Use continuous ingest plus graph-informed promotion.

Why relevant:
- matches concept "memory lifecycle"
- active project decision
- supersedes older batch-only analysis idea
- supported by session X / episode Y
```

### 11. Hygiene and maintenance

The service periodically enqueues hygiene jobs:

- catch up stale sessions;
- reconcile duplicate candidates;
- resolve conflict candidates;
- compact graph clutter;
- rebuild Chroma index;
- repair FTS index;
- refresh salience.

Hygiene should be conservative. It should not silently delete memory. Prefer lowering salience, marking superseded, or flagging review.

## Local HTTP API

The initial API shape should be small and local-only:

```text
GET  /health
GET  /v1/capabilities
GET  /v1/status
POST /v1/observe
POST /v1/sessions/{session_id}/sync
POST /v1/sessions/{session_id}/finalize
POST /v1/recall/search
GET  /v1/jobs/{job_id}
GET  /v1/sessions/{session_id}/interpretation
```

Requests should be quick and idempotent. Long work returns job IDs.

Exact request and response schemas should be defined during the service foundation phase, not in this architecture document.

## Durable jobs

FastAPI request handlers should not do heavy memory work. They should enqueue jobs in SQLite.

Job table shape:

```text
jobs
- id
- kind
- status: queued | claimed | running | completed | failed | cancelled
- payload_json
- priority
- due_at
- attempts
- max_attempts
- run_id
- claimed_at
- claimed_by
- started_at
- heartbeat_at
- lease_expires_at
- running_pid
- finished_at
- exit_code
- result_json
- last_error
- created_at
- updated_at
```

Implemented job kinds:

- `process_transcript` for raw FTS indexing and deterministic Phase 5A structure rebuilding;
- `interpret_session` for replaceable Phase 5B session interpretation.

Future job kinds:

- `ingest_session`;
- `segment_episodes`;
- `update_session_map`;
- `extract_candidates`;
- `reconcile_candidates`;
- `promote_artifacts`;
- `update_indexes`;
- `hygiene_reconcile_duplicates`;
- `hygiene_resolve_conflicts`;
- `hygiene_compact_graph`;
- `catchup_stale_sessions`.

On startup, stale running jobs should be returned to the queue or marked failed according to retry policy.

## Storage model

Canonical local storage should live under a new memory-owned directory:

```text
~/.pi/memory/
  memory.db
  chroma/
  logs/
  server.json
```

This path is intentionally separate from the current observer store.

### SQLite canonical tables

Current canonical and derived tables:

- `sessions`;
- `transcripts`;
- `observations`;
- `transcript_entries`;
- `jobs`;
- `analysis_runs`;
- `activity_units`;
- `episodes`;
- `episode_manifests`;
- `session_snapshot_shells`;
- `session_interpretation_snapshots`.

Future durable-memory tables:

- `memory_artifacts`;
- `artifact_revisions`;
- `source_spans`;
- `memory_nodes`;
- `memory_edges`;
- `artifact_sources`.

SQLite owns:

- transcript metadata and raw entry records;
- session state;
- rebuildable activity units;
- episode boundaries;
- episode manifests and source-span references;
- analysis runs;
- deterministic session snapshot shells as a Phase 5A compatibility artifact;
- replaceable current session interpretation snapshots;
- durable memory artifacts;
- artifact revisions;
- graph nodes and edges;
- source spans and provenance;
- job queue and scheduling;
- artifact status, salience, and confidence.

### ChromaDB vector index

ChromaDB indexes selected text from SQLite:

- artifact statements;
- artifact titles;
- source excerpts;
- episode summaries;
- concept labels and descriptions.

Chroma metadata should reference SQLite IDs. It should not duplicate canonical state.

Invariant:

> Anything in ChromaDB must be reconstructable from SQLite.

ChromaDB is never canonical memory.

### Graph backend

Start with graph-shaped SQLite tables as canonical graph storage.

Use ChromaDB for semantic candidate generation. Optionally use NetworkX for in-memory graph analysis or hygiene jobs. Consider Kùzu later only if graph traversal or path queries become difficult in SQLite.

Do not start with Neo4j, ArangoDB, RDF, or another external graph server.

## Phased implementation plan

Implementation should proceed through runnable vertical slices. The ordering matters: prove the service boundary and durable ingest before building graph/reconciliation complexity.

### Phase 0: Lock architecture and cutover stance

Purpose: turn the north-star direction into repo-local guidance before code churn.

Deliverables:

- Add this architecture document.
- Record the clean-cutover stance.
- Record canonical-vs-derived storage rules.
- Record the phased implementation sequence.
- Decide whether implementation will use the existing `pi-observer` package path, a new `pi-memory` package, or a transition path.

Validation:

- The document exists and is discoverable.
- The document is consistent with issue #123.
- Open decisions are explicit.

Deferred:

- API schemas.
- DB implementation.
- LLM prompts.
- Runtime changes.

### Phase 1: Service skeleton and Pi bootstrap

Purpose: prove the runtime boundary between Pi and the Python memory service.

Deliverables:

- FastAPI app.
- Fixed localhost port.
- `GET /health` endpoint.
- `GET /v1/status` endpoint.
- Python CLI, such as `pi-memory serve` and `pi-memory status`.
- Pi extension startup check.
- Pi service bootstrap if health check fails.
- Server lock or pid metadata file.
- Graceful degraded behavior if the service cannot start.

Validation:

- Service starts via CLI.
- Pi can start service if it is not running.
- Multiple Pi sessions do not spawn duplicate servers.
- Health and status endpoints work.
- Startup failures are visible and non-fatal to the Pi session.

Deferred:

- Transcript parsing.
- Jobs.
- Recall.
- ChromaDB.
- LLM analysis.

### Phase 2: Canonical SQLite store and transcript ingest

Purpose: establish full transcript capture as the source of truth.

Deliverables:

- SQLite `memory.db` initialization.
- Initial tables for sessions, observations, and transcript events.
- `POST /v1/observe` endpoint.
- Session registration/upsert.
- Transcript cursor tracking.
- Incremental transcript ingest from `transcript_path`.
- Parser support for Pi transcript format.
- Idempotent observe behavior.

Validation:

- Repeated observe calls do not duplicate events.
- Cursor advances correctly.
- Partial trailing JSONL lines are handled safely.
- Restart does not lose cursor state.
- Parser and ingest tests cover representative transcripts.

Deferred:

- Episode segmentation.
- Artifact extraction.
- Graph memory.
- ChromaDB indexing.

### Phase 3: Durable job queue and worker loop

Purpose: create the durable execution spine for heavy work.

Deliverables:

- SQLite `jobs` table.
- Internal worker/scheduler loop in the service process.
- Job claim/lease semantics.
- Startup recovery for stale running jobs.
- `GET /v1/jobs/{job_id}` endpoint.
- Job enqueue from `/v1/observe`.
- Initial job kinds such as `ingest_session`, `catchup_stale_sessions`, and a test/no-op job.

Validation:

- Jobs run outside request handlers.
- Failed jobs record errors.
- Stale running jobs recover on restart.
- Duplicate jobs are coalesced or harmless.
- Service can shut down and resume work.

Deferred:

- LLM analysis.
- Promotion logic.
- Hygiene sophistication.

### Phase 4: Baseline recall over raw transcripts

Purpose: get end-to-end recall working before durable memory exists, while establishing raw transcript recall as a durable provenance and fallback layer rather than throwaway scaffolding.

Implemented in `pi-memory`:

- SQLite FTS5 projection `transcript_entries_fts` over canonical `transcript_entries`.
- Derived, rebuildable FTS content populated from deterministic extracted search text by `process_transcript` jobs.
- `RecallSearchService` searches FTS and joins matches back to canonical transcript and session rows.
- `POST /v1/recall/search` endpoint returning typed `raw_transcript` source-backed results.
- Local CLI recall via `pi-memory recall --query --db-url [--json]` for isolated databases.
- Recall results include session identity, transcript entry/source context, excerpt text, rank/score information, and basic match reason.
- `branch_summary.summary` is indexed into raw FTS as source-backed deterministic text, without indexing `details` values.

Validation:

- API recall queries return source-backed raw transcript results.
- CLI recall queries return the same source-backed layer, including JSON output when requested.
- Recall works after database and service restart because canonical transcript entries and the rebuildable FTS projection are persisted in SQLite.
- Recall does not require ChromaDB, embeddings, graph records, snapshots, candidates, durable artifacts, or LLM output.
- No Pi recall tool validation is required in Phase 4 because Pi tool wiring and cutover are deferred.

Deferred:

- Pi recall tool wiring and Pi extension recall-surface cutover.
- Session snapshots and candidate extraction.
- Durable memory artifacts.
- Graph traversal and graph-backed recall.
- Supersession and reconciliation.
- LLM extraction, embeddings, ChromaDB indexing, and hybrid recall.

### Phase 5A: Deterministic episode manifests and snapshot shells

Purpose: introduce deterministic transcript structure without permanent memory promotion or model-backed interpretation.

Implemented in `pi-memory`:

- `analysis_runs` table.
- `activity_units` table.
- `episodes` table.
- `episode_manifests` table.
- `session_snapshot_shells` table.
- `Transcript` parent lineage fields `parent_transcript_path` and `parent_transcript_id`.
- Deterministic activity normalization over canonical `transcript_entries`.
- Tool call/result pairing by `toolCall.id == message.toolCallId`.
- Tool receipts with bounded metadata, counts, and source references rather than full raw output copies.
- Activity unit `source_origin` values: `local`, `inherited`, `mixed`, or `unknown`.
- Episode segmentation on compaction, timestamp gap, transcript/session scope, and EOF/current cursor.
- Bounded episode manifests with `activity_map_json` included/omitted ranges; included activity-map entries carry `source_origin` and `claim_source_allowed`.
- Manifest `tool_result_text_byte_count` and source spans.
- Deterministic session snapshot shells with counts, analyzed-through offsets, and `snapshot_json.ready_for_interpretation` / `blocked_reason` readiness gates.
- `snapshot_json.fork` readiness metadata, origin counts, and `claim_source_activity_count`.
- `process_transcript` job persistence that rebuilds Phase 5A rows idempotently after FTS indexing.

`process_transcript` result JSON now includes a safe nested `phase_5a` object:

```text
phase_5a
- analysis_run_id
- status
- activity_count
- episode_count
- manifest_count
- snapshot_shell_id (Phase 5A compatibility artifact)
- analyzed_through_entry_id
- analyzed_through_byte_offset
```

Validation:

- Running `process_transcript` indexes raw transcript FTS and rebuilds deterministic Phase 5A rows in the same transaction.
- Re-running analysis for a transcript replaces derived rows without duplicating activities, episodes, manifests, or session snapshot shells.
- Episode boundaries do not depend on raw byte size, raw tool output size, or entry count.
- Episode manifests reference raw source spans and do not duplicate full raw tool output.
- Snapshot shells contain no goal, summary, candidate decisions, candidate constraints, candidate knowledge, candidate preferences, candidate patterns, or open questions.
- `SessionSnapshotShell.status` remains a shell lifecycle status; Phase 5B no longer uses shell rows as the active interpretation handoff.

Handed off to Phase 5B:

- Rolling session interpretation now consumes Phase 5A rows through `EpisodePacket` / `InterpretationPacket` read models.
- `session_interpretation_snapshots` is now the active replaceable interpretation surface.
- Snapshot shells can remain in existing local databases without destructive migration.

Deferred to later phases:

- Durable project memory.
- Cross-session reconciliation.
- Graph promotion.

### Phase 5B: LLM-backed rolling session interpretation

Purpose: consume Phase 5A episodes/manifests and bounded raw source spans to maintain a replaceable working interpretation of a session without durable memory promotion.

Implemented in `pi-memory`:

- `session_interpretation_snapshots` table for one current interpretation per session.
- `interpret_session` durable job kind.
- `EpisodePacket`, `InterpretationPacket`, and `InterpretationReadiness` read models over Phase 5A rows.
- Readiness computed without `session_snapshot_shells`.
- Blocked snapshots for `phase_5a_not_ready`, `parent_transcript_not_ingested`, and `source_origin_incomplete`.
- Skipped snapshots for sessions with no claim-source activities.
- Structured `InterpretationOutput` contract with claim kinds `decision`, `constraint`, `knowledge`, `preference`, `pattern`, and `action`.
- Citation validation that rejects unknown source refs and rejects claims supported only by inherited or unknown-origin refs.
- Interpreter seam with deterministic local implementation for tests/development and opt-in PydanticAI provider calls for real interpretation; model metadata and prompt/schema versions are recorded on completed snapshots.
- Post-Phase5A enqueueing: `process_transcript` enqueues `interpret_session` after raw FTS indexing and deterministic structure persistence.
- Stale interpretation job no-op behavior. Auto-enqueued jobs carry `process_job_id` because SQLite may reuse analysis ids after Phase 5A rebuilds.
- Read-only inspection via `GET /v1/sessions/{session_id}/interpretation` and `pi-memory interpretation --session-id --db-url [--json]`.
- Model-agnostic interpreter configuration via `pi-memory config`, `~/.pi/memory/config.json`, and environment overrides `PI_MEMORY_INTERPRETER_MODE` / `PI_MEMORY_INTERPRETER_MODEL`.

Real provider calls are opt-in. The default interpreter mode remains `deterministic`, which makes no network calls. To enable PydanticAI-backed interpretation, set `interpreter_mode = pydantic-ai` and configure `interpretation_model` with any PydanticAI-supported model string, such as `anthropic:claude-sonnet-4-5` or `openai:gpt-4o`. `pi-memory` does not store API keys; provider credentials stay in the environment variables expected by PydanticAI/provider packages, such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

Current interpretation fields include:

- goal;
- summary;
- source-cited candidate claims;
- open questions;
- citations;
- analyzed transcript entry/byte offsets;
- origin counts and claim-source counts;
- prompt, schema, and model metadata;
- snapshot `schema_version`.

Validation:

- New transcript events enqueue interpretation after deterministic structure is rebuilt.
- New completed/blocked/skipped interpretations replace the prior current interpretation.
- Interpretations cite source refs from episode packets.
- Candidate claims require at least one `local` or `mixed` claim-source-allowed source ref.
- Inherited activity may support summary/context/open questions but not claims by itself.
- Interpretation can be rerun from canonical transcript data plus Phase 5A derived structure.
- Phase 5B remains independent of `session_snapshot_shells`; existing shell tables can remain without destructive migration.

Deferred:

- Provider-specific tuning, model routing, cost tracking, and throttling beyond the generic PydanticAI adapter.
- Durable project memory.
- Cross-session reconciliation.
- Graph promotion.
- Pi recall/tool UI exposure for interpretation snapshots.

### Phase 6: Durable artifact and graph schema

Purpose: create the durable memory substrate.

Deliverables:

- `memory_artifacts` table.
- `artifact_revisions` table.
- `source_spans` table.
- `memory_nodes` table.
- `memory_edges` table.
- `artifact_sources` table.
- Artifact states: active, superseded, conflicting, retracted, archived, needs_review.
- Artifact kinds: decision, constraint, knowledge, preference, pattern, open question, action.
- Basic graph writes from artifacts to concepts, source spans, sessions, episodes, files, or modules.

Validation:

- Session snapshots can produce candidate artifacts.
- Candidate artifacts can be written as active artifacts.
- Source spans link back to transcript offsets.
- Graph neighborhood queries work in SQLite.

Deferred:

- Complex reconciliation.
- Supersession automation.
- Advanced graph algorithms.

### Phase 7: ChromaDB projection and hybrid recall

Purpose: add performant semantic retrieval while keeping SQLite canonical.

Deliverables:

- Chroma collection or collections.
- Vector index abstraction.
- Indexing for artifact statements, titles, selected source spans, episode summaries, and concept labels.
- Rebuild command or job.
- Hybrid recall across FTS, ChromaDB, and graph neighborhood expansion.
- Chroma metadata that references SQLite IDs.

Validation:

- Chroma collection can be deleted and rebuilt from SQLite.
- Recall degrades safely if ChromaDB is stale or unavailable.
- Vector hits resolve back to SQLite artifacts.
- Metadata filters work for project, kind, and status.

Deferred:

- Advanced ranking.
- Sophisticated graph algorithms.
- Automatic supersession.

### Phase 8: Promotion and reconciliation

Purpose: make durable memory evolve safely.

Deliverables:

- Candidate promotion job.
- Graph-neighborhood candidate selection.
- Relationship classifier for new, duplicate, refines, supersedes, contradicts, supports, related, and unrelated.
- Conservative mutation rules.
- Revision and supersession edge writes.
- Conflict edges and review statuses.

Validation:

- Later artifacts can supersede older artifacts with evidence.
- Related artifacts remain separate.
- Conflicts are visible, not silently resolved.
- Recall defaults to active artifacts but can expose history.
- Semantic-only similarity cannot auto-supersede prior memory.

Deferred:

- Fully automatic global truth maintenance.
- User review UI unless proven necessary.

### Phase 9: Hygiene and maintenance

Purpose: prevent memory degradation over time.

Deliverables:

- Scheduled catch-up for stale sessions.
- Reprocessing for failed analyses.
- Rebuild jobs for derived indexes.
- Duplicate-active-artifact detection.
- Unresolved-conflict detection.
- Salience and usage tracking.
- Maintenance CLI commands such as jobs, reindex, reprocess-session, and graph-status.

Validation:

- Restart catches missed work.
- Index rebuild is safe.
- Hygiene jobs are idempotent.
- Cleanup uses explicit status transitions instead of silent deletion.

Deferred:

- Rich UI.
- Complex graph algorithms unless proven necessary.

### Phase 10: Clean cutover from old observer

Purpose: replace the current observer behavior.

Deliverables:

- Current Pi observer hooks route to the new service.
- Old recall path is replaced by service-backed recall.
- Old CLI commands are removed, redirected, or documented as obsolete.
- Old observer DB and Chroma paths are no longer used by the active memory system.
- Install and package registration use the new service behavior.
- Docs are updated.

Validation:

- Fresh install works with the new memory service.
- No old observer state is required.
- Python tests and TypeScript checks pass.
- Manual Pi launch starts or reconnects to the service.
- Service-backed recall works in a fresh environment.
- Old observer paths are not read except for explicit cleanup or status messaging if added later.

Deferred:

- Historical migration.
- Backwards compatibility.

## Milestone grouping

The phases can be grouped into larger implementation milestones.

### Milestone 1: Service foundation

Includes phases 0 through 3.

Outcome:

```text
Python service runs, Pi starts it, transcripts are captured, and durable jobs work.
```

### Milestone 2: Useful recall

Includes phases 4 and 5.

Outcome:

```text
Recall works from raw transcripts and session snapshots; graph promotion is not required yet.
```

### Milestone 3: Durable graph memory

Includes phases 6 through 8.

Outcome:

```text
Source-backed durable memory artifacts exist, are indexed in ChromaDB, and are connected by graph relationships.
```

### Milestone 4: Production cutover

Includes phases 9 and 10.

Outcome:

```text
The old observer is replaced by the service-backed memory system, with hygiene and recovery behavior in place.
```

## Critical decisions before implementation

Resolve these before or during Phase 1:

1. Package and command naming:
   - keep `pi-observer`;
   - rename to `pi-memory`;
   - split during transition, then remove the old observer.

2. Fixed localhost port and collision behavior.

3. Whether the first implementation happens in the existing `pi-observer` package path or a new package path.

4. First recall target:
   - raw transcript FTS first;
   - session snapshots first;
   - wait for durable artifacts.

5. Initial API schemas for observe, status, jobs, and recall.

6. Initial SQLite schema and migration policy for the new clean store.

7. Initial artifact taxonomy and status set.

8. Model/provider configuration for analysis jobs.

9. Episode segmentation strategy:
   - resolved for Phase 5A as transcript/session scope, compaction, one-hour timestamp gap, and EOF/current cursor;
   - raw byte size, raw tool output size, and entry count are not episode boundaries.

10. Rolling analysis thresholds:
    - Phase 5A only uses deterministic lifecycle boundaries plus bounded manifest budgets;
    - Phase 5B currently enqueues interpretation after each successful `process_transcript` rebuild;
    - future throttling triggers may include turns, transcript bytes, token estimates, lifecycle events, compaction, and stale-session catch-up.

11. Finalization triggers:
    - compaction;
    - shutdown;
    - stale-session catch-up;
    - manual command.

12. Recall response shape and Pi rendering behavior.

## Validation expectations for the full system

The completed memory system should satisfy these checks:

- service starts on a fixed localhost port;
- Pi starts or reconnects to the service if absent;
- duplicate observe calls are idempotent;
- transcript cursoring works across restarts;
- service restart recovers stale jobs;
- shutdown is not required for finalization;
- ChromaDB can be rebuilt from SQLite;
- recall returns source-backed artifacts or excerpts;
- recall explains why results were returned;
- superseded/conflicting memory remains inspectable;
- old observer stores are not required;
- no heavy memory logic runs in the Pi extension.

## Sequencing guidance

Do not start with the graph reconciler.

Start with:

```text
service -> ingest -> jobs -> basic recall
```

Then add:

```text
snapshots -> artifacts -> graph -> promotion
```

The graph is the north star, but the first implementation risk is the service boundary and durable ingest pipeline.
