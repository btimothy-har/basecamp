# CLAUDE.md

## What is basecamp

A multi-project workspace launcher for AI coding agents. Configures project directories, manages isolated git worktrees, and provides semantic memory over past sessions.

Two packages, one pi extension:

| Package | Directory | Purpose |
|---------|-----------|---------|
| `basecamp-core` | `core/` | CLI tool — project config, prompt assembly, session launch |
| `basecamp-observer` | `observer/` | Semantic memory — session ingestion, LLM extraction, vector search, `recall` CLI |

See `core/CLAUDE.md` and `observer/CLAUDE.md` for package-specific architecture and decisions.

## Repo Map

```
core/src/core/
├── main.py                     # Click entry point
├── cli/                        # One module per command (launch, open, worker, etc.)
├── config/project.py           # ProjectConfig Pydantic model
├── git/
│   ├── repo.py                 # Git utilities (is_git_repo, get_repo_name, etc.)
│   └── worktrees.py            # Worktree CRUD (create, list, remove, get_or_create)
├── prompts/
│   ├── system.py               # Prompt assembly pipeline
│   ├── working_styles.py       # Style discovery and loading
│   ├── project_context.py      # Context file resolution
│   ├── _system_prompts/        # Package defaults (environment.md, system.md)
│   ├── _working_styles/        # Package defaults (engineering.md, advisor.md)
│   └── logseq/                 # Logseq session prompts (reflect, plan)
├── worker/
│   ├── models.py               # WorkerEntry Pydantic model, WorkerStatus enum
│   ├── index.py                # File-backed per-project worker index with locking
│   └── operations.py           # Worker lifecycle: create, dispatch, close, list
├── settings.py                 # File-backed config with locking
├── constants.py                # Path constants
└── exceptions.py               # Exception hierarchy

observer/src/observer/
├── cli/
│   ├── observer.py             # Click entry point (db, setup, ingest, reprocess)
│   └── recall.py               # Click entry point — recall CLI for semantic search
├── data/                       # SQLAlchemy schemas + Pydantic domain models
├── llm/
│   ├── agents.py               # 3 lazy pydantic-ai agents + output schemas
│   └── prompts/                # .txt prompt templates (PEP 562 lazy load)
├── pipeline/
│   ├── parser.py               # JSONL transcript parsing + ParsedEvent
│   ├── grouping.py             # RawEvent → WorkItem classification
│   ├── refinement.py           # WorkItemRefiner + EventRefiner
│   ├── extraction.py           # Transcript-level section extraction
│   └── indexing.py             # ChromaDB embedding
├── search.py                   # Hybrid KNN+FTS retrieval + scoring
├── services/                   # DB, config, chroma, migrations, registration
└── migrations/                 # Schema migrations

extension/                      # Pi extension — system prompts, skills, agents, hooks

core/tests/                     # pytest suite for basecamp-core
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over Claude's behavior but means basecamp must provide everything Claude Code's default prompt would (environment context, tool guidance, etc.). Claude Code still appends its own tool definitions section — that's the one thing we can't control.

Prompts are layered (environment → working style → system → project context) so that each concern is independently overridable. Project context is injected via a SessionStart hook rather than included in the system prompt — this places it alongside CLAUDE.md in the conversation, not buried in the system prompt.

Assembled prompts are persisted to `~/.basecamp/.cached/{project}/prompt.md` so dispatch workers can inherit the parent session's prompt without re-assembling.

### Extension

All skills, agents, hooks, and system prompts are bundled in a single pi extension (`extension/`). This replaces the previous Claude Code plugin system.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars, then forwards them through the terminal multiplexer (tmux/Kitty) so they survive the pane boundary. Dispatch workers bulk-forward all `BASECAMP_*` vars from the parent process — this means new vars added to launch automatically propagate without cherry-picking.

`BASECAMP_REPO` is always the git repo name, never a worktree label or directory name. This ensures observer can scope searches consistently regardless of whether the session is in a worktree.

### Worktree Design

Worktrees live in `~/.worktrees/<repo>/<label>/` rather than inside the repo to avoid polluting project directories. Metadata is stored separately in `.meta/` JSON files for the same reason. The `-l` flag is intentionally opt-in — most sessions don't need worktree isolation.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode for both packages)
- **Lint**: `uv run ruff check` / `uv run ruff format`

### Testing

- **Run**: `uv run pytest` from repo root
- **Config**: root `pyproject.toml` — `testpaths = ["core/tests"]`, `pythonpath = ["core/src"]`
- **Core tests** use temporary git repos (`temp_git_repo` fixture) and mock terminal backends. Observer is not required — `TESTING=1` is set by pytest config.
- **Observer tests** are in `observer/tests/` (not currently run from root pytest config). Core tests don't depend on observer.
