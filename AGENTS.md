# AGENTS.md

## What is basecamp

A multi-project workspace launcher for AI coding agents. Configures project directories, manages isolated git worktrees, and provides semantic memory over past sessions.

Two packages, one pi extension:

| Package | Directory | Purpose |
|---------|-----------|---------|
| `basecamp-core` | `core/` | CLI tool — project config and setup |
| `basecamp-observer` | `observer/` | Semantic memory — session ingestion, LLM extraction, vector search, `recall` CLI |

See `core/AGENTS.md` and `observer/AGENTS.md` for package-specific architecture and decisions.

## Repo Map

```
core/src/core/
├── main.py                     # Click entry point (setup, project commands)
├── cli/
│   ├── project.py              # Interactive project CRUD
│   └── setup.py                # Environment setup (prerequisites, scaffolding)
├── config/
│   ├── project.py              # ProjectConfig Pydantic model, load/save
│   └── directories.py          # Directory resolution and validation
├── settings.py                 # File-backed config with locking
├── constants.py                # Path constants
├── exceptions.py               # Exception hierarchy
├── ui.py                       # Console output helpers
└── utils.py                    # Shared utilities

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

extension/                      # Pi extension
├── package.json                # Extension manifest (extensions, skills, prompts)
├── config.ts                   # Config reader (~/.basecamp/config.json)
├── context.ts                  # Context assembly (git, tools, skills, projects)
├── core/
│   ├── src/
│   │   ├── session.ts          # Session bootstrap (flags, env, worktree, cwd)
│   │   ├── prompt.ts           # System prompt assembly pipeline
│   │   ├── worktree.ts         # Worktree CRUD + bash/tool guards
│   │   ├── handoff.ts          # /handoff slash command
│   │   ├── open.ts             # /open slash command
│   │   └── system-prompts/     # Bundled prompts (environment, system, styles)
│   ├── skills/                 # discovery skill
│   └── prompts/                # Logseq session prompts (reflect, plan)
├── agents/
│   ├── src/
│   │   ├── tool.ts             # Agent dispatch tool registration
│   │   ├── executor.ts         # Subagent process management
│   │   ├── discovery.ts        # Agent definition discovery (project, user, builtin)
│   │   ├── commands.ts         # /agents slash command
│   │   ├── skills.ts           # Skill discovery for subagents
│   │   └── types.ts            # Agent/skill type definitions
│   └── builtin/                # Built-in agent definitions (scout, worker, etc.)
├── git/
│   └── src/                    # Git guards, PR workflow commands
├── observer/
│   └── src/                    # Observer integration (session ingest trigger)
├── engineering/skills/         # Code review, context gathering, python dev
└── data/skills/                # SQL, data warehousing

core/tests/                     # pytest suite for basecamp-core
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Extension

All skills, agents, hooks, and system prompts are bundled in a single pi extension (`extension/`). This replaces the previous Claude Code plugin system.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

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
- **Core tests** cover settings and config. `TESTING=1` is set by pytest config.
- **Observer tests** are in `observer/tests/` (not currently run from root pytest config). Core tests don't depend on observer.
