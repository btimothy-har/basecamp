# AGENTS.md

## What is basecamp

A project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and provides semantic memory over past sessions.

One Python package, one Pi extension:

| Package | Directory | Purpose |
|---------|-----------|---------|
| `basecamp` | `cli/` | CLI tools for setup/config, observer ingestion, semantic search, and `recall` |

Package-specific architecture lives in the repo map below.

## Repo Map

```
cli/src/basecamp/
├── main.py                     # Click entry point (setup, config)
├── cli/
│   ├── project.py              # Interactive project CRUD used by config menu
│   └── setup.py                # Environment setup (prerequisites, scaffolding)
├── config/
│   ├── project.py              # ProjectConfig Pydantic model, load/save
│   └── directories.py          # Directory storage helpers
├── settings.py                 # File-backed config with locking + migrations
├── constants.py                # Path constants
├── exceptions.py               # Exception hierarchy
├── ui.py                       # Console output helpers
└── utils.py                    # Shared utilities

cli/src/observer/
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

pi-ext/                         # Pi extension package
├── package.json                # Extension manifest (extensions, skills, prompts)
├── platform/                   # Shared extension platform modules
│   ├── catalog.ts              # Capability catalog providers/queries
│   ├── config.ts               # Config reader + SessionState resolver
│   ├── context.ts              # Prompt context builders + AGENTS.md discovery
│   ├── exec.ts                 # Cwd-aware exec seam for extension modules
│   ├── skill-content.ts        # Shared skill file loading/rendering helpers
│   ├── skill-tracker.ts        # Shared skill invocation state
│   ├── templates.ts            # Markdown template loader
│   └── utils.ts                # Shared small utilities
├── core/
│   ├── src/
│   │   ├── runtime/            # Session bootstrap, worktree setup, tool guards
│   │   ├── prompt/             # System prompt assembly + context injection
│   │   │   └── system-prompts/ # Bundled environment/style/language prompts
│   │   ├── tools/              # discover, skill, escalate, catalog providers
│   │   ├── ui/                 # Header, footer, session title widget
│   │   ├── commands/           # /open command
│   │   └── index.ts            # Core extension registration
│   ├── skills/                 # gather + pi-development skills
│   └── prompts/                # Logseq session prompts (reflect, plan)
├── workflow/
│   ├── src/
│   │   ├── agents/             # Agent discovery, dispatch tool, commands, skills
│   │   ├── planning/           # plan tool, review UI, plan commands
│   │   ├── tasks/              # Goal/task tools, state, rendering, commands
│   │   └── index.ts            # Workflow extension registration
│   ├── agents/builtin/         # Built-in agent definitions
│   └── skills/                 # agents + planning skills
├── git/
│   ├── src/                    # Git guards, PR workflow commands, pr_publish tool
│   └── resources/              # PR workflow prompt templates
├── observer/
│   ├── src/                    # Observer integration (session ingest trigger)
│   └── skills/                 # recall skill
└── engineering/                # Engineering prompts + skills (code review, Python, marimo, SQL, data warehousing)

cli/tests/                      # pytest suite for basecamp CLI and observer
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Extension

All skills, agents, hooks, and system prompts are bundled in a single pi extension (`pi-ext/`). This replaces the previous Claude Code plugin system.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

`BASECAMP_REPO` is always the git repo name, never a worktree label or directory name. This ensures observer can scope searches consistently regardless of whether the session is in a worktree. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are set to the active worktree values, or empty strings when no worktree is active.

### Worktree Design

Worktrees live in `~/.worktrees/<repo>/<label>/` rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, approved implementation plans activate a worktree inside the Pi session, resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode)
- **Lint**: `uv run ruff check` / `uv run ruff format`

### Testing

- **Run**: `uv run pytest` from repo root
- **Config**: root `pyproject.toml` — `testpaths = ["cli/tests"]`, `pythonpath = ["cli/src"]`
- **Basecamp tests** cover settings and config. `TESTING=1` is set by pytest config.
- **Observer tests** live under `cli/tests/observer/` and run from the root pytest config.
