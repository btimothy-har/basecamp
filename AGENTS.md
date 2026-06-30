# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

Root-level products:

| Product | Directory | Purpose |
|---------|-----------|---------|
| `basecamp` | `src/basecamp/` | Python composition CLI for setup/projects/install |
| `basecamp-core` | `core/config/` | Generic settings/files/paths/exceptions |
| `basecamp-workspace` | `workspace/projects/` | Project config and interactive projects menu |
| `pi-swarm` | `pi-swarm/` | Async-agent bounded context for protocol docs, Pi-side agent behavior, and daemon CLI/runtime |
| Basecamp Pi packages | `core/pi`, `workspace/pi`, `pi-*` | Pi packages for project context, session UI, worktrees, workflow, git, and engineering skills |

Package-specific architecture lives in the repo map below.

## Repo Map

```
src/basecamp/                  # Root Python composition package
├── cli.py                      # Click entry point (setup, projects, install, companion)
├── setup.py                    # Environment setup (prerequisites, scaffolding)
└── installer.py                # Bootstrap/reconfiguration install orchestration

core/config/                    # basecamp-core Python package
├── src/basecamp_core/          # Generic settings/files/paths/exceptions
└── tests/                      # basecamp-core pytest suite

workspace/projects/             # basecamp-workspace Python package
├── src/basecamp_workspace/     # Project config and interactive projects menu
└── tests/                      # workspace pytest suite

pi-swarm/                      # Async-agent bounded context
├── protocol/                   # Protocol docs and frame fixtures
├── extension/                  # TypeScript Pi-side agent tools, launch policy, daemon client, reporter
└── cli/                        # Python daemon CLI/runtime package

core/pi/                       # pi-core TypeScript package: registries, session, state, model aliases, workspace primitives
pi-ui/                         # Session UI package: footer, title, mode editor
workspace/pi/                  # pi-workspace TypeScript package: project context + workspace service
pi-tasks/                      # Tasks, planning, workflow skills
pi-git/                        # Code walkthrough, review packet, and prompt-only PR creation workflows
pi-bash-reviewer/              # LLM bash reviewer: gates risky git/gh/shell commands
pi-engineering/                # Engineering tools and skills
pi-browser/                    # Browser automation tools (puppeteer-core over CDP)
pi-companion/                  # Companion bounded context
├── pi/                        # TypeScript session hooks, tmux panes, analysis registration
└── tui/                       # Python companion TUI/analyzer package
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Pi Packages

Core public session/project/workspace/workflow/git/model-alias/capability/engineering behavior is split across pluggable Pi packages (`core/pi`, `workspace/pi`, `pi-ui`, `pi-tasks`, `pi-git`, `pi-bash-reviewer`, `pi-engineering`, `pi-companion/pi`). Async-agent protocol, Pi-side launch/tool behavior, and daemon runtime ownership live in the top-level `pi-swarm/` context.

### Model Aliases

Model alias resolution is owned by `core/pi/src/model-aliases`, backed by `~/.pi/basecamp/core/model-aliases.json` with schema `{ "version": 1, "aliases": { "fast": "claude-haiku-4-5" } }`. `core/pi/src/platform/model-aliases.ts` is only the provider seam; it must not read config, define aliases, or own model-selection policy.

### Process-Scoped Singletons

Mutable state shared across Pi packages or required to survive `/reload` must live on `globalThis` behind a `Symbol.for("basecamp.*")` key, never a module-level `let`. On `/reload`, Pi re-imports every extension with fresh module instances (`moduleCache: false`), so each extension can hold its own copy of a shared module; only `globalThis`-backed state stays process-scoped and reload-stable. State read inside a `session_start` handler must initialize defensively (e.g. `ensureCurrentSessionStateForEvent`) rather than assuming another extension's `session_start` ran first — cross-extension handler ordering is not guaranteed and changes on reload. See `core/pi/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. `BASECAMP_REPO` is always the git repo name, never a worktree label or directory name. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are set to the active worktree values, or empty strings when no worktree is active.

The worktree setup hook (`worktree_setup` in `~/.pi/basecamp/config.json`, run by `pi-tasks` on creation of a new execution worktree) additionally exposes `BASECAMP_REPO_ROOT` (the protected checkout path) to the setup command for the duration of that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live in `~/.worktrees/<repo>/<label>/` rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, approved implementation plans activate a worktree inside the Pi session, resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode; installs `basecamp`, then registers the Basecamp Pi package)
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `make lint` runs checks for all Pi packages after Python lint/format checks
- **Fix**: `make fix` runs Python fixes plus lint/format fixes for all Pi packages

### Testing

- **Run all**: `make test` from repo root runs Python pytest plus all Pi package TypeScript tests.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths = ["core/config/tests", "workspace/projects/tests", "pi-companion/tui/tests"]`, `pythonpath` includes `src`, `core/config/src`, `workspace/projects/src`, `pi-swarm/cli/src`, and `pi-companion/tui/src`.
- **TypeScript**: `make test` covers `core/pi`, `pi-ui`, `workspace/pi`, `pi-tasks`, `pi-git`, `pi-engineering`, `pi-browser`, `pi-companion/pi`, and `pi-swarm/extension`.
- **Basecamp Python tests** live under `core/config/tests/`, `workspace/projects/tests/`, and `pi-companion/tui/tests/`.
