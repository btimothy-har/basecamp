# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides semantic memory over past sessions.

Root-level products:

| Product | Directory | Purpose |
|---------|-----------|---------|
| `basecamp` | `basecamp-cli/` | Python CLI for setup/config and project configuration |
| Basecamp Pi extension | `pi-extension/` | Pi package for project context, session UI, worktrees, workflow, git, and engineering skills |
| `pi-observer` | `pi-observer/` | Python CLI for semantic-memory operations plus Pi package for ingestion hooks and recall |

Package-specific architecture lives in the repo map below.

## Repo Map

```
basecamp-cli/
├── pyproject.toml              # Python package exposing the `basecamp` CLI
├── src/basecamp/
│   ├── main.py                 # Click entry point (setup, config)
│   ├── cli/
│   │   ├── config.py           # Interactive configuration menu
│   │   ├── project.py          # Interactive project CRUD used by config menu
│   │   └── setup.py            # Environment setup (prerequisites, scaffolding)
│   ├── config/                 # ProjectConfig model and directory helpers
│   ├── settings.py             # File-backed config with locking + migrations
│   ├── constants.py            # Path constants
│   ├── exceptions.py           # Exception hierarchy
│   ├── ui.py                   # Console output helpers
│   └── utils.py                # Shared utilities
└── tests/basecamp/             # pytest suite for Basecamp settings/config

pi-extension/                   # Core Pi package
├── package.json                # Extension manifest (extensions, skills, prompts)
├── index.ts                    # Registers the composed extension modules
└── src/
    ├── platform/               # Shared extension platform modules
    ├── session/                # Session lifecycle hooks, UI, mode commands
    ├── capabilities/           # Skill tool, skill lifecycle tracking, catalog providers
    ├── model-aliases/          # Native model alias config reader/provider registration
    ├── projects/               # Project config/state, prompt assembly, context injection, header
    ├── workspace/              # Repo/worktree service, guards, affinity, commands, unsafe-edit
    ├── workflow/               # Agents, planning, tasks, escalation, workflow skills
    ├── git/                    # Git guards, PR/issue workflow commands, publish tools
    ├── state/                  # Session state persistence
    └── engineering/            # Engineering runtime tools, prompts, and engineering/Pi skills

pi-observer/
├── pyproject.toml              # Python package exposing the `pi-observer` CLI
├── package.json                # Pi package manifest for observer integration
├── extension/src/              # Pi extension for session ingest trigger and recall tool
├── skills/recall/              # Recall skill
├── src/pi_observer/
│   ├── cli/
│   │   ├── main.py             # Click entry point (db, setup, ingest, reprocess)
│   │   └── recall.py           # Recall subcommand implementation
│   ├── data/                   # SQLAlchemy schemas + Pydantic domain models
│   ├── llm/                    # pydantic-ai agents + prompt templates
│   ├── pipeline/               # Parsing, grouping, refinement, extraction, indexing
│   ├── search.py               # Hybrid KNN+FTS retrieval + scoring
│   ├── services/               # DB, config, chroma, migrations, registration
│   └── migrations/             # Schema migrations
└── tests/                      # pytest suite for observer CLI/pipeline/search
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Pi Packages

Core session, project, workspace, workflow, git, model-alias, capability, and engineering functionality is bundled in `pi-extension/`. Observer integration is bundled separately in `pi-observer/`, which owns ingestion hooks, the recall tool, and the recall skill alongside its Python CLI and pipeline.

### Model Aliases

Model alias resolution is owned by `pi-extension/src/model-aliases`, backed by `~/.pi/model-aliases/config.json` with schema `{ "version": 1, "aliases": { "fast": "claude-haiku-4-5" } }`. `pi-extension/src/platform/model-aliases.ts` is only the provider seam; it must not read config, define aliases, or own model-selection policy.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. `BASECAMP_REPO` is always the git repo name, never a worktree label or directory name. Observer scopes memory by repo/project/session, not the current active worktree. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are set to the active worktree values, or empty strings when no worktree is active.

### Worktree Design

Worktrees live in `~/.worktrees/<repo>/<label>/` rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, approved implementation plans activate a worktree inside the Pi session, resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode; installs `basecamp` and `pi-observer`, then registers both Pi packages)
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `npm --prefix pi-extension run check` and `npm --prefix pi-observer run check`
- **Fix**: `make fix` runs Python fixes and both TypeScript package fix/format commands

### Testing

- **Run all**: `make test` from repo root runs Python pytest plus the pi-extension TypeScript unit suites.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths = ["basecamp-cli/tests", "pi-observer/tests"]`, `pythonpath = ["basecamp-cli/src", "pi-observer/src"]`.
- **TypeScript**: `npm --prefix pi-extension test` runs the session/state/project/workspace/git/workflow unit suites.
- **Basecamp tests** live under `basecamp-cli/tests/` and cover settings/config.
- **Observer tests** live under `pi-observer/tests/` and cover observer CLI, pipeline, search, and storage. `TESTING=1` is set by pytest config.
