# Memory Agent North Star

Status: active `pi-memory` architecture and implementation roadmap. `pi-memory` has implemented Phase 4 raw transcript recall, Phase 5A deterministic transcript structure/fork provenance, Phase 5B replaceable session interpretation over chronological activity-text packets, Phase 5C persisted interpretation quality reports, and Phase 6 durable memory promotion with a unified rebuildable semantic projection. `pi-observer` is deprecated and removed from active install/test/package-registration paths; Pi recall tool wiring remains deferred.

Related issue: [#123](https://github.com/btimothy-har/basecamp/issues/123)

## Context

`pi-observer` previously provided semantic recall over Pi coding sessions by ingesting transcript JSONL, extracting structured artifacts, storing those artifacts in SQLite, and indexing them in ChromaDB. That implementation proved the value of local session recall, but the active memory system is now `pi-memory` and should not be constrained by the old observer lifecycle, schema, or package boundaries.

The north-star system is a clean cutover: a Python-first local memory service that continuously captures full Pi transcripts, derives evolving session understanding, promotes durable source-backed memory artifacts into an associative graph, and serves explainable recall through a thin Pi adapter.

The deprecated observer is useful inspiration. It should not be treated as a compatibility target.

## One-sentence north star

Build a Python-first local memory service that continuously captures full Pi transcripts, derives replaceable session-level understanding, promotes durable source-backed memory artifacts into an associative graph, and serves explainable recall through a thin Pi adapter using SQLite as canonical storage and ChromaDB as a rebuildable semantic index.

## Clean cutover stance

This design intentionally replaces the deprecated observer behavior rather than migrating or preserving historical observer stores.

The new system should not require compatibility with:

- the existing `~/.pi/observer` data directory;
- deprecated observer SQLite schemas;
- deprecated observer Chroma collections;
- deprecated extraction artifact shapes;
- deprecated CLI behavior;
- deprecated Pi extension orchestration behavior.

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

## Deprecated observer as inspiration

The old observer had useful ideas:

- it stores full raw transcript payloads;
- it uses SQLite for durable local data;
- it uses ChromaDB for semantic retrieval;
- it extracts summaries, decisions, constraints, knowledge, and actions;
- it exposes recall through Pi tooling.

The new design should carry forward those lessons while avoiding the constraints that made the observer shape hard to evolve:

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
- send session observations, transcript path, launch `cwd`, and lifecycle events;
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
  -> activity units / episodes
  -> activity text
  -> replaceable session interpretation
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

Raw tool output remains in `transcript_entries.raw_line`. `activity_units.activity_text` is the derived chronological text spine for downstream interpretation: non-tool activity receives deterministic text during Phase 5A persistence, and paired tool call/result activity is marked pending until an LLM summarizer writes a compact source-backed summary. Activity text is derived and rebuildable; it does not replace canonical raw transcript rows.

Episode manifests store bounded `activity_map_json` with included and omitted ranges, counts, receipts, and source-span references so later interpretation can trace activity text back to raw transcript rows when needed.

### 5. Tool activity summarization

Before session interpretation, a durable `summarize_tool_activities` job fills pending tool-pair `activity_units.activity_text` rows for the target analysis run.

Each model call receives exactly one tool call/result pair and returns exactly one structured summary for that `activity_unit_id`. Calls run concurrently in bounded `asyncio.gather` windows. The default window is 10; `PI_MEMORY_TOOL_SUMMARY_CONCURRENCY` or `pi-memory config --tool-summary-concurrency` can raise or lower it within the validated range of 1 through 100. `tool_summary_model` / `PI_MEMORY_TOOL_SUMMARY_MODEL` can use a separate PydanticAI-supported model string, falling back to `interpretation_model` when unset.

Per-activity failures are recorded on the affected activity row with sanitized error metadata and do not prevent other tool summaries from completing. Failed or pending tool activities remain chronological context but do not expose claim citation ids.

### 6. Rolling session interpretation

After deterministic structure and tool activity text exist, an interpretation job maintains a replaceable session interpretation over cleaned chronological activity records.

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

Each new completed, blocked, or skipped interpretation replaces the previous current interpretation for that session. This prevents cumulative analysis from creating permanent duplicate or stale artifacts. The interpretation stage consumes `EpisodePacket` read models built from chronological `activity_units.activity_text`, episode manifests, and source-ref metadata. Prompt rendering keeps activity text and direct `claim_source_ref_ids` in chronological order while omitting heavyweight raw transcript JSON. Server-side validation still uses the full packet/source-ref model. Interpretation does not replace the underlying activity rows and does not promote durable memory.

`session_snapshot_shells` remains a non-destructive Phase 5A compatibility artifact for now, but it is no longer the active Phase 5B handoff model. Phase 5B computes readiness directly from transcript lineage, latest completed `analysis_runs`, and `activity_units.source_origin`; it builds interpretation packets from `episodes` and `episode_manifests` after readiness is known.

### 6.5. Interpretation quality reports

Every non-stale interpretation snapshot enqueues an `assess_interpretation_quality` durable job. Quality is persisted separately from interpretation content in `session_interpretation_quality_reports`, keyed one-to-one by `snapshot_id`. The report is derived state over the current replaceable interpretation; it is not a durable memory artifact and does not mutate interpretation claims.

The quality report deliberately separates axes that dashboards and future promotion logic should not collapse:

- processing state remains on `session_interpretation_snapshots.status` (`completed`, `blocked`, `skipped_no_claim_sources`);
- derivation/currentness is `derivation_status` (`current`, `outdated`, `superseded`) plus the read-model boolean `is_current`;
- deterministic integrity is `deterministic_status` (`passed`, `failed`, `not_applicable`) and structured deterministic findings;
- semantic quality is `semantic_status` (`passed`, `degraded`, `failed`, `not_assessed`, `assessment_failed`) plus structured semantic findings;
- promotion eligibility is the conservative `promotable` boolean;
- wall-clock timestamps are recency metadata, not quality.

Transcript age is not quality. An old report can remain promotable if it is current for its snapshot and deterministic checks pass, even when semantic quality is degraded. A new report can be non-promotable if deterministic integrity fails, semantic assessment is pending/failed, or the derivation is outdated.

Completed/current snapshots first run deterministic checks for facts the service can prove locally: analyzed-through identity, required interpretation payload fields, claim presence for interpretable packets, citation/source-ref resolution, local/mixed claim-source eligibility, source-origin completeness, cited activity text completion, prompt version, and safe model metadata. Only completed/current/deterministic-passed packets call the configured semantic quality assessor. Blocked and skipped snapshots receive non-applicable deterministic reports without a model call.

Semantic assessment uses a PydanticAI-supported `quality_model` / `PI_MEMORY_QUALITY_MODEL`. If unset, it falls back to `tool_summary_model`, then `interpretation_model`. The quality prompt receives a bounded packet containing interpretation JSON, citations, chronological `activity_units.activity_text`, source-ref ids, and quality/deterministic metadata. It does not query or send full `transcript_entries.raw_line` transcript rows, and `pi-memory` does not persist provider API keys. Provider credentials remain in environment variables used by PydanticAI/provider packages.

If semantic assessment fails transiently, the durable job retry policy applies. On the final failed attempt, `pi-memory` writes a visible safe report with `quality_status = assessment_failed` and `semantic_status = assessment_failed`, storing only safe error type metadata so dashboards are not blind and provider error bodies are not persisted.

Read surfaces are implemented for API, CLI, and TUI inspection:

```text
GET /v1/sessions/{session_id}/quality
GET /v1/quality/reports
GET /v1/quality/reports/sample
pi-memory quality --session-id ... --db-url ... [--json]
pi-memory quality-list --db-url ... [filters] [--json]
pi-memory quality-sample --db-url ... [filters] [--json]
pi-memory quality-tui --db-url ...
```

The quality TUI consumes these persisted reports and interpretation failure metadata. It does not own quality logic, reinterpretation, repair, manual claim editing, approval workflow, or Phase 6 promotion writes.

### 7. Candidate extraction

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

### 8. Graph mapping

Candidates are attached to the memory graph.

Graph nodes may include:

- Artifact;
- ArtifactRevision;
- Concept;
- Session;
- Episode;
- SourceSpan;
- Project;
- SessionCwd;
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

### 9. Reconciliation

Promotion is a reconciliation process. For each candidate, the service finds nearby existing memory by:

- same canonical key;
- shared concepts;
- same files/modules/entities;
- same decision or constraint topic;
- semantic similarity via ChromaDB;
- recently active related sessions.

Current Phase 6 relation assessment is deterministic and session-cwd scoped. It classifies a candidate against resolved promoted durable-memory hits from the same launch `cwd` using:

- `novel`;
- `duplicate`;
- `reinforces`;
- `refines`;
- `conflicts`;
- `supersedes`;
- `stale_signal`.

Implemented mutation rules are conservative:

```text
novel
  -> eligible for promotion when reducer thresholds pass

duplicate
  -> reject duplicate candidate

reinforces
  -> promote when confidence is sufficient

refines
  -> promote refined candidate when confidence is sufficient

conflicts
  -> quarantine for inspection

supersedes
  -> promote candidate and archive superseded memory when confidence is sufficient

stale_signal
  -> reject as stale signal
```

Semantic similarity alone must not auto-supersede. Broader graph reconciliation and richer edge semantics remain future work.

### 10. Promotion

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

The API shape stays small and local-only. Current implemented endpoints are:

```text
GET  /health
GET  /v1/status
POST /v1/observe
GET  /v1/jobs/{job_id}
POST /v1/recall/search              # raw transcript FTS recall
GET  /v1/sessions/{session_id}/interpretation
GET  /v1/sessions/{session_id}/quality
GET  /v1/quality/reports
GET  /v1/quality/reports/sample
GET  /v1/durable-memory
GET  /v1/durable-memory/{memory_id}
GET  /v1/durable-memory/{memory_id}/audit
GET  /v1/memory-projections
```

Planned endpoint candidates remain separate from the implemented surface:

```text
GET  /v1/capabilities
POST /v1/sessions/{session_id}/sync
POST /v1/sessions/{session_id}/finalize
```

Requests should be quick and idempotent. Long work returns job IDs.

Exact request and response schemas should live with the implementation and tests, not only in this architecture document.

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
- `summarize_tool_activities` for filling pending tool-pair activity text with source-backed per-tool summaries;
- `interpret_session` for replaceable Phase 5B session interpretation over chronological activity text;
- `assess_interpretation_quality` for persisted Phase 5C quality reports;
- `project_memory_records` for quality-report projection and all-record rebuild/upsert passes;
- `promote_durable_memory` for quality-gated durable memory promotion.

Future job kinds:

- `ingest_session`;
- `segment_episodes`;
- `update_session_map`;
- `extract_candidates`;
- `reconcile_candidates`;
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

This path is intentionally separate from deprecated observer stores.

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
- `session_interpretation_snapshots`;
- `session_interpretation_quality_reports`;
- `durable_memory_items`;
- `durable_memory_sources`;
- `durable_memory_relations`;
- `durable_memory_audit_events`;
- `memory_projection_records`.

Future broader graph/artifact tables:

- `memory_artifacts`;
- `artifact_revisions`;
- `source_spans`;
- `memory_nodes`;
- `memory_edges`;
- `artifact_sources`.

SQLite owns:

- transcript metadata and raw entry records;
- session state;
- rebuildable activity units, including derived `activity_text` projection fields;
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

Purpose: turn the north-star direction into codebase-local guidance before code churn.

Deliverables:

- Add this architecture document.
- Record the clean-cutover stance.
- Record canonical-vs-derived storage rules.
- Record the phased implementation sequence.
- Record `pi-memory` as the active package path and command surface.

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

- Rolling session interpretation now consumes Phase 5A rows through chronological activity-text `EpisodePacket` / `InterpretationPacket` read models.
- `session_interpretation_snapshots` is now the active replaceable interpretation surface.
- Snapshot shells can remain in existing local databases without destructive migration.

Deferred to later phases:

- Durable project memory.
- Cross-session reconciliation.
- Graph promotion.

### Phase 5B: LLM-backed rolling session interpretation

Purpose: consume Phase 5A activity units, episode manifests, and source provenance to maintain a replaceable working interpretation of a session without durable memory promotion.

Implemented in `pi-memory`:

- Inline activity-text projection on `activity_units`: `activity_text`, `activity_text_kind`, `activity_text_status`, and `activity_text_metadata_json`.
- Deterministic activity text for non-tool activity during Phase 5A persistence.
- `summarize_tool_activities` durable job kind between `process_transcript` and `interpret_session`.
- Per-tool PydanticAI summarization where each prompt receives exactly one tool call/result pair and returns one summary for that activity unit.
- Bounded concurrent tool summarization windows, configured by `tool_summary_concurrency` / `PI_MEMORY_TOOL_SUMMARY_CONCURRENCY` with a default of 10 and valid range of 1 through 100.
- Separate `tool_summary_model` / `PI_MEMORY_TOOL_SUMMARY_MODEL`, falling back to `interpretation_model` when unset.
- `session_interpretation_snapshots` table for one current interpretation per session.
- `interpret_session` durable job kind over completed chronological activity text.
- `EpisodePacket`, `InterpretationPacket`, and `InterpretationReadiness` read models over Phase 5A rows and activity text.
- Readiness computed without `session_snapshot_shells`.
- Blocked snapshots for `phase_5a_not_ready`, `parent_transcript_not_ingested`, and `source_origin_incomplete`.
- Skipped snapshots for sessions with no claim-source activities.
- Structured `InterpretationOutput` contract with claim kinds `decision`, `constraint`, `knowledge`, `preference`, `pattern`, and `action`.
- Citation validation that rejects unknown source refs, rejects claims supported only by inherited or unknown-origin refs, and rejects empty claim lists for interpretable packets with claim sources.
- Interpreter seam with PydanticAI as the runtime implementation and deterministic local implementation retained only for tests/development injection; model metadata and prompt/schema versions are recorded on completed snapshots.
- Job chain: `process_transcript` enqueues `summarize_tool_activities` after raw FTS indexing and deterministic structure persistence; `summarize_tool_activities` then enqueues `interpret_session`.
- Stale interpretation and tool-summary job no-op behavior. Auto-enqueued jobs carry `process_job_id` because SQLite may reuse analysis ids after Phase 5A rebuilds.
- Slim chronological prompt rendering: activity records carry `activity_text` plus direct `source_ref_ids` / `claim_source_ref_ids`; raw JSON transcript lines and heavyweight source-ref metadata stay out of the session interpretation prompt.
- Read-only inspection via `GET /v1/sessions/{session_id}/interpretation` and `pi-memory interpretation --session-id --db-url [--json]`.
- Model-agnostic PydanticAI configuration via `pi-memory config`, `~/.pi/memory/config.json`, `PI_MEMORY_INTERPRETATION_MODEL`, `PI_MEMORY_TOOL_SUMMARY_MODEL`, and `PI_MEMORY_TOOL_SUMMARY_CONCURRENCY`.

PydanticAI-backed interpretation requires `interpretation_model` to be configured with any PydanticAI-supported model string, such as `anthropic:claude-sonnet-4-6` or `openai:gpt-4o`. Tool summarization can use a separate lower-latency model such as `anthropic:claude-haiku-4-5`. When jobs run, `pi-memory` sends source-backed tool activity packets and chronological session activity-text packets to the configured PydanticAI provider. `pi-memory` does not store API keys; provider credentials stay in the environment variables expected by PydanticAI/provider packages, such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

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

- New transcript events enqueue tool summarization after deterministic structure is rebuilt.
- Tool summarization writes completed, failed, or skipped activity-text status per tool-pair activity without mutating canonical transcript rows.
- New completed/blocked/skipped interpretations replace the prior current interpretation.
- Interpretations cite source refs from chronological activity packets.
- Candidate claims require at least one `local` or `mixed` claim-source-allowed source ref.
- Interpretable packets with claim sources must produce at least one source-backed claim; claimless summaries fail validation rather than silently replacing the snapshot.
- Inherited activity may support summary/context/open questions but not claims by itself.
- Interpretation can be rerun from canonical transcript data plus Phase 5A derived structure and activity-text projection.
- Phase 5B remains independent of `session_snapshot_shells`; existing shell tables can remain without destructive migration.

Deferred:

- Provider-specific tuning, model routing, cost tracking, and throttling beyond the generic PydanticAI adapter.
- Durable project memory.
- Cross-session reconciliation.
- Graph promotion.
- Pi recall/tool UI exposure for interpretation snapshots.

### Phase 5C: Always-on interpretation quality reports

Purpose: assess replaceable session interpretations before any durable memory promotion, keeping currentness, deterministic integrity, semantic quality, and promotion eligibility separate.

Implemented in `pi-memory`:

- `session_interpretation_quality_reports` table keyed by `snapshot_id` with cascade delete from replaceable interpretation snapshots.
- `assess_interpretation_quality` durable job kind, automatically enqueued after every completed, blocked, or skipped non-stale `interpret_session` snapshot write.
- `quality_model` / `PI_MEMORY_QUALITY_MODEL` configuration, falling back to `tool_summary_model` and then `interpretation_model`.
- Strict quality contracts for findings, claim assessments, missing high-signal items, semantic output, and persisted report drafts.
- Deterministic integrity checks for citation/source-ref resolution, local/mixed claim-source eligibility, claim presence, source-origin completeness, analyzed-through identity, tool/activity-text completion, prompt version, and model metadata.
- Bounded `QualityPacket` read model over interpretation JSON, citations, chronological activity text, and source refs; full raw transcript rows and provider secrets stay out of quality prompts.
- PydanticAI-backed semantic quality assessor plus deterministic test/development assessor injection seam.
- Final failure policy that writes a safe visible `assessment_failed` report after retries are exhausted.
- Read-only reporting via `GET /v1/sessions/{session_id}/quality`, `GET /v1/quality/reports`, `GET /v1/quality/reports/sample`, `pi-memory quality`, `pi-memory quality-list`, `pi-memory quality-sample`, and `pi-memory quality-tui`.

Status taxonomy:

- `quality_status`: `healthy`, `degraded`, `failed`, `not_assessed`, `assessment_failed`.
- `quality_reason`: stable reason for non-healthy statuses, such as `blocked_interpretation`, `skipped_no_claim_sources`, `outdated_derivation`, `superseded_snapshot`, `deterministic_integrity_failed`, `semantic_assessment_pending`, `semantic_degraded`, `semantic_failed`, or `semantic_assessment_failed`.
- `derivation_status`: `current`, `outdated`, `superseded`; this is derived-state consistency, not transcript age.
- `deterministic_status`: `passed`, `failed`, `not_applicable`.
- `semantic_status`: `passed`, `degraded`, `failed`, `not_assessed`, `assessment_failed`.
- `promotable`: true when the snapshot is completed, derivation is current, deterministic checks passed, and either `semantic_status = passed` with `quality_status = healthy`, or `semantic_status = degraded` with `quality_status = degraded`.

Validation:

- Completed/current deterministic-passed snapshots call the quality assessor and persist semantic findings.
- Blocked and skipped snapshots persist non-applicable quality reports without model calls.
- Replaced snapshot quality jobs complete as stale no-ops; outdated derivations are reported separately from semantic quality.
- Provider failures retry through durable jobs; final failure persists `assessment_failed` without leaking provider error bodies.
- Quality read surfaces return JSON-safe reports with session metadata including `cwd`, `assessment_state`, `is_current`, and severity `finding_counts` for future dashboards.

Deferred:

- Browser/Django UI.
- Dashboards beyond the current quality TUI.
- Reinterpretation repair loop or automatic mutation of interpretation claims.
- Manual claim editing, approval workflow, or annotation UI.
- Broader graph memory beyond Phase 6 durable relation/projection records.

### Phase 6: Durable memory promotion and unified semantic projection

Purpose: automatically convert quality-gated interpretation claims into source-cited durable memory items while indexing short-term and long-term memory records in one rebuildable semantic projection.

Implemented in `pi-memory`:

- Canonical durable-memory tables owned by SQLite:
  - `durable_memory_items` for candidate/promoted/quarantined/rejected/archived memory state;
  - `durable_memory_sources` for source-ref links back to interpretation evidence;
  - `durable_memory_relations` for `duplicate` / `reinforces` / `refines` / `conflicts` / `supersedes` / `stale_signal` relation metadata;
  - `durable_memory_audit_events` for immutable status and derivation audit events;
  - `memory_projection_records` for rebuildable Chroma projection metadata.
- Durable statuses: `candidate`, `promoted`, `quarantined`, `rejected`, and `archived`.
- Archive reasons: `superseded`, `stale`, `manually_retired`, and `source_invalidated`, with `superseded_by_id` for supersession chains.
- One `pi-memory` Chroma collection, `pi_memory_records`, used as a unified projection rather than separate short-term/long-term collections.
- Projection metadata that distinguishes:
  - `record_type = session_claim`, `memory_layer = short_term` for eligible quality-assessed session interpretation claims;
  - `record_type = durable_memory`, `memory_layer = long_term` for durable memory candidates/items.
- Chroma projection seam with deterministic tests and a Chroma-backed implementation using the configured embedding model from `PI_MEMORY_EMBEDDING_MODEL` or `pi-memory config --embedding-model`.
- Short-term claim projection via `project_session_claims(...)` and `project_memory_records` jobs.
- Durable candidate construction directly from source-cited interpretation claims; there is no separate candidate-extraction LLM in this phase.
- Quality-report eligibility evaluation that consumes persisted `SessionInterpretationQualityReport` fields, finding codes, claim assessments, currentness, and `promotable` as authoritative input.
- Single-call candidate evaluator over one candidate plus bounded source evidence, with provider-backed and deterministic implementations.
- Chroma-assisted relation assessment that upserts/query candidates and promoted durable memories, resolves every hit through SQLite, then classifies relations deterministically.
- Session-cwd-scoped relation comparison: candidate and related durable memories are compared only when they share the same `MemorySession.cwd`; missing cwd skips relation comparison and classifies the candidate as `novel` with no resolved hits.
- Deterministic reducer that maps eligibility, evaluator metrics, and relation assessments into `promoted`, `quarantined`, `rejected`, or supersession/archive transitions with reason codes and audit events.
- Durable job wiring:
  - `project_memory_records` for quality-report projection and all-record rebuild/upsert passes, with per-record failure metadata persisted for retry and inspection;
  - `promote_durable_memory` for report-level promotion through eligibility, evaluation, relation assessment, reducer persistence, and projection refresh.
- Read-only inspection surfaces:
  - `GET /v1/durable-memory`;
  - `GET /v1/durable-memory/{memory_id}`;
  - `GET /v1/durable-memory/{memory_id}/audit`;
  - `GET /v1/memory-projections`;
  - `pi-memory durable`;
  - `pi-memory durable-list`;
  - `pi-memory durable-audit`;
  - `pi-memory projection-list`.

Core invariants:

- SQLite is canonical for durable memory state, sources, relations, audit events, jobs, quality reports, transcripts, and projection metadata.
- Chroma is disposable and rebuildable from SQLite. It is never canonical memory.
- Every Chroma hit must resolve through SQLite before relation decisions or future recall packets are built.
- Default recall visibility is limited to promoted durable memory and eligible short-term/session records; rejected, quarantined, archived, failed, and audit-only records remain inspectable but hidden from default recall views.
- Raw transcript recall remains SQLite FTS-backed; Phase 6 does not index every raw transcript entry into Chroma.
- Promotion consumes persisted Phase 5C quality reports. It does not recompute citation/source-origin/currentness/episode-coverage checks.
- Provider calls remain behind candidate-evaluation seams and are not made by read-only inspection surfaces.
- Inspection is audit-oriented and read-only; there is no manual approval workflow for every memory.

Validation:

- Schema tests cover durable memory/projection constraints and relationships.
- Projection tests cover deterministic and Chroma-seam metadata behaviour.
- Promotion tests cover eligibility blocking, candidate evaluation, relation assessment, reducer decisions, job retry/idempotency, supersession archival, and read-only inspection.
- Full `pi-memory/tests` passes with deterministic seams and no provider calls.

Deferred:

- Final unified recall endpoint/tool and Pi/Basecamp active-coding prompt injection.
- Full Textual durable-memory dashboard.
- Browser/Django UI.
- Manual repair/edit/approval workflow.
- Broad graph memory, advanced graph algorithms, and global truth maintenance.
- Indexing every raw transcript entry into Chroma.
- Historical `pi-observer` SQLite or Chroma migration.

### Phase 7: Unified recall over short-term and durable memory

Purpose: serve explainable recall packets from the canonical SQLite substrate plus rebuildable semantic projection.

Planned deliverables:

- A unified recall API/tool that queries the one `pi_memory_records` Chroma collection with metadata filters and resolves every hit through SQLite.
- Short-term view over eligible session/episode claim records.
- Long-term view over `record_type = durable_memory` and `status = promoted` records.
- Hybrid ranking that can combine raw transcript FTS, semantic projection hits, recency, source quality, and relation context.
- Recall packets with source citations, memory layer labels, quality/projection status, and explanation of why each item was returned.

Validation:

- Recall never trusts Chroma metadata without SQLite resolution.
- Recall degrades safely if Chroma is stale, missing, or unavailable.
- Hidden states (`rejected`, `quarantined`, `archived`, failed projection records, audit-only rows) stay out of default recall unless explicitly requested.

Deferred:

- Prompt injection into active Pi/Basecamp coding sessions until packet shape and ranking are proven.
- Advanced graph neighborhood expansion.

### Phase 8: Graph memory and reconciliation automation

Purpose: make durable memory evolve safely beyond the initial status/relation substrate.

Planned deliverables:

- Graph-style nodes and edges for concepts, source spans, files/modules, sessions, goals, questions, and durable memory items when the SQLite relation substrate is no longer enough.
- Graph-neighborhood candidate selection for richer relation context than top-K semantic projection hits alone.
- Conservative global reconciliation rules for supersession, conflict visibility, archival, and revision-style history.

Validation:

- Later memories can supersede older memories with source-backed evidence.
- Related memories remain separate unless deterministic reducer rules archive a specific target.
- Conflicts are visible, not silently resolved.
- Semantic similarity alone cannot auto-supersede prior memory.

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

Purpose: keep `pi-memory` as the only active memory subsystem.

Deliverables:

- Deprecated observer hooks are removed from active package registration.
- Old recall path is replaced by service-backed recall.
- Old CLI commands are removed from active install/test/lint paths and documented as obsolete if the source remains in the repository.
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
pi-memory is the only active memory subsystem, with hygiene and recovery behavior in place.
```

## Critical decisions

Resolved and remaining decisions for the `pi-memory` roadmap:

1. Package and command naming:
   - resolved to `pi-memory` as the active package and command.

2. Fixed localhost port and collision behavior.

3. First recall target:
   - raw transcript FTS first;
   - session snapshots first;
   - wait for durable artifacts.

4. Initial API schemas for observe, status, jobs, and recall.

5. Initial SQLite schema and migration policy for the new clean store.

6. Initial artifact taxonomy and status set.

7. Model/provider configuration for analysis jobs.

8. Episode segmentation strategy:
   - resolved for Phase 5A as transcript/session scope, compaction, one-hour timestamp gap, and EOF/current cursor;
   - raw byte size, raw tool output size, and entry count are not episode boundaries.

9. Rolling analysis thresholds:
    - Phase 5A only uses deterministic lifecycle boundaries plus bounded manifest budgets;
    - Phase 5B currently enqueues `summarize_tool_activities` after each successful `process_transcript` rebuild, then enqueues `interpret_session` after tool activity text is filled;
    - future throttling triggers may include turns, transcript bytes, token estimates, lifecycle events, compaction, and stale-session catch-up.

10. Finalization triggers:
    - compaction;
    - shutdown;
    - stale-session catch-up;
    - manual command.

11. Recall response shape and Pi rendering behavior.

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
