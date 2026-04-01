# observer/CLAUDE.md

## What is basecamp-observer

Semantic memory for Claude Code sessions. Ingests session transcripts, extracts structured knowledge via LLM, embeds it into ChromaDB, and exposes search via the `recall` CLI. The goal: Claude can recall decisions, patterns, and context from past sessions.

## Data Pipeline

### Ingestion (hook-triggered)

Companion hooks call `observer ingest` on SessionEnd and PreCompact:

1. **Register session** — `register_session()` resolves the repo root (handles worktrees via `--git-common-dir`), detects worktree label, and upserts Project/Worktree/Transcript records.

2. **Parse transcript** — `TranscriptParser.parse()` reads JSONL from the transcript's cursor offset (incremental — only new lines since last ingest). Skips malformed JSON, missing timestamps, and unreliable event types. Each parsed event becomes a `RawEvent` row.

3. **Group into work items** — `EventGrouper.group_batch()` classifies raw events into **work items** — logical units of activity:

   | WorkItemType | What it groups | Refinement |
   |--------------|---------------|------------|
   | `prompt` | User message | Extracted as-is |
   | `tool_pair` | tool_use + matching tool_result(s) | LLM summary |
   | `thinking` | Extended thinking block | LLM summary |
   | `response` | Agent text response | Text extraction |
   | `task_management` | TaskCreate/Update/List/Get calls | Skipped (TERMINAL) |
   | `orphaned_result` | tool_result with no matching tool_use | Skipped (TERMINAL) |

   Each work item references its source `event_ids` (JSON-serialized list) and progresses through stages: UNREFINED → REFINING → REFINED (or TERMINAL for skipped types, ERROR on failure).

### Processing (background)

`observer process <session_id>` runs as a detached background process:

1. **Refine** — `WorkItemRefiner.refine()` claims unrefined work items via atomic UPDATE (optimistic CAS) and summarizes them via LLM (ThreadPoolExecutor, max 15 workers). Each type gets its own handler (see table above). Output is a `TranscriptEvent` — the refined text representation of the work item.

2. **Extract** — `TranscriptExtractor.extract_transcript()` sends all refined transcript events to a single LLM call, producing 5 section types as `Artifact` rows (summary, knowledge, decisions, constraints, actions). Upserts by (transcript_id, section_type).

3. **Index** — `SearchIndexer.index_pending()` embeds artifacts with sentence-transformers (`all-MiniLM-L6-v2`, 384 dimensions), upserts embeddings + metadata into ChromaDB, and updates `content_hash`/`indexed_at` on the SQLite artifact row.

### Search (recall CLI)

Search is exposed via the `recall` CLI (second entry point in `basecamp-observer`), which wraps the engine directly:
- `search_transcripts` — hybrid search over summaries (ChromaDB KNN + FTS5) for orientation retrieval
- `search_artifacts` — hybrid search over non-summary sections (ChromaDB KNN + FTS5), scored with time decay
- `get_session` — direct lookup by session_id (used by dispatch)

Search is scoped to current project via `BASECAMP_REPO`. Pass `--cross-project` to search across all projects. The current session is auto-excluded via `CLAUDE_SESSION_ID`.

### Configuration

`~/.basecamp/observer/config.json` — persistent settings:
- `extraction_model` / `summary_model` — which Claude model to use for LLM calls
- `mode` — "on" (full pipeline) or "off" (ingestion only, no LLM calls)

Database migrations tracked via a `schema_version` table. Run pending migrations with `observer db migrate`.

### Storage

All data lives in `~/.basecamp/` as local files:
- `~/.basecamp/observer.db` — SQLite database (relational model, FTS5)
- `~/.basecamp/chroma/` — ChromaDB persistent client (vector embeddings, HNSW index)

## Design Decisions

### LLM calls use `claude -p` subprocess, not the Anthropic SDK

The `Agent` class wraps the Claude CLI in subprocess mode (`claude -p --output-format json`). This reuses existing CLI auth and routing — no API keys to manage, no SDK dependency, model selection follows the user's Claude config. The trade-off is subprocess overhead and no streaming, but extraction is batch work where latency doesn't matter. The agent disables all Claude Code features (settings, MCP, tools, slash commands) to get a clean LLM-only interface.

### Transcript-level extraction

Extraction is a single-pass operation: all events are refined first, then the full transcript is sent to one LLM call. This gives the LLM complete session context for better summaries, and keeps the model simple — one extraction per transcript, upserted by (transcript_id, section_type).

### Five fixed section types

Artifacts are constrained to five `SectionType` values: summary, knowledge, decisions, constraints, actions. Fixed types enable targeted retrieval — artifact search filters out summaries, transcript search only uses summaries. The constraint produces more consistent, searchable output than free-form sections would.

### Staged pipeline with atomic claiming

The pipeline has explicit stages: parse → group → refine → extract → index. Each stage runs independently and is idempotent. Work items use an atomic UPDATE with optimistic CAS (Compare-And-Swap) for claiming, preventing concurrent `observer process` invocations from double-processing. SQLite's file-level write lock ensures only one writer at a time, making the UPDATE inherently atomic. A 30-second busy timeout handles write contention from overlapping process runs.

### SQLite + ChromaDB (no server required)

SQLite handles relational storage and keyword search (FTS5). ChromaDB handles vector storage and KNN search (HNSW index, cosine distance). Both are embedded — no server process, no Docker container, no network dependency. The embedding model is `all-MiniLM-L6-v2` (384 dimensions) — small enough to run locally without GPU.

FTS5 uses a virtual table (`artifacts_fts`) synced via SQL triggers on the artifacts table, with the `porter` tokenizer for stemming. ChromaDB stores embeddings in a single `artifacts` collection with metadata filters for project/session/worktree/date scoping.

### Search scoring uses time decay

Results blend semantic similarity (60%) and keyword relevance (40%) into a relevance signal, then combine that (80%) with a recency bonus (up to 20%). Time decay follows a power law — 50% recency at 30 days, never reaching zero.
