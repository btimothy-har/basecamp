# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

Root-level products:

| Product | Directory | Purpose |
|---------|-----------|---------|
| `basecamp` | `src/basecamp/` | Python composition CLI for setup/config/install |
| `basecamp-core` | `core/config/` | Generic settings/files/paths/exceptions |
| `basecamp-workspace` | `workspace/projects/` | Project config and interactive config menu |
| `pi-swarm` | `pi-swarm/` | Async-agent bounded context for protocol docs, Pi-side agent behavior, and daemon CLI/runtime |
| Basecamp Pi packages | `core/pi`, `workspace/pi`, `pi-*` | Pi packages for project context, session UI, worktrees, workflow, git, and engineering skills |

Package-specific architecture lives in the repo map below.

## Repo Map

```
src/basecamp/                  # Root Python composition package
├── cli.py                      # Click entry point (setup, config, install, companion)
├── setup.py                    # Environment setup (prerequisites, scaffolding)
└── installer.py                # Bootstrap/reconfiguration install orchestration

core/config/                    # basecamp-core Python package
├── src/basecamp_core/          # Generic settings/files/paths/exceptions
└── tests/                      # basecamp-core pytest suite

workspace/projects/             # basecamp-workspace Python package
├── src/basecamp_workspace/     # Project config and interactive config menu
└── tests/                      # workspace pytest suite

pi-swarm/                      # Async-agent bounded context
├── protocol/                   # Protocol docs and frame fixtures
├── extension/                  # TypeScript Pi-side agent tools, launch policy, daemon client, reporter
└── cli/                        # Python daemon CLI/runtime package

pi-extension/                   # Public extension package (current session runtime and adapters)
├── package.json                # Extension manifest (extensions, skills, prompts)
├── index.ts                    # Registers the composed extension modules
└── src/
    ├── platform/               # Shared extension platform modules
    ├── session/                # Session lifecycle hooks, UI, mode commands
    ├── capabilities/           # Skill tool, skill lifecycle tracking, catalog providers
    ├── model-aliases/          # Native model alias config reader/provider registration
    ├── projects/               # Project config/state, prompt assembly, context injection, header
    ├── workspace/              # Repo/worktree service, guards, affinity, commands, unsafe-edit
    ├── workflow/               # Planning, tasks, escalation, workflow skills
    ├── git/                    # Git guards, PR/issue workflow commands, publish tools
    ├── state/                  # Session state persistence
    └── engineering/            # Engineering runtime tools, prompts, and engineering/Pi skills
```

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Pi Packages

Core public session/project/workspace/workflow/git/model-alias/capability/engineering behavior is currently bundled in `pi-extension/`. Async-agent protocol, Pi-side launch/tool behavior, and daemon runtime ownership live in the top-level `pi-swarm/` context.

### Model Aliases

Model alias resolution is owned by `pi-extension/src/model-aliases`, backed by `~/.pi/model-aliases/config.json` with schema `{ "version": 1, "aliases": { "fast": "claude-haiku-4-5" } }`. `pi-extension/src/platform/model-aliases.ts` is only the provider seam; it must not read config, define aliases, or own model-selection policy.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. `BASECAMP_REPO` is always the git repo name, never a worktree label or directory name. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are set to the active worktree values, or empty strings when no worktree is active.

### Worktree Design

Worktrees live in `~/.worktrees/<repo>/<label>/` rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, approved implementation plans activate a worktree inside the Pi session, resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode; installs `basecamp`, then registers the Basecamp Pi package)
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `npm --prefix pi-extension run check` and `npm --prefix pi-swarm/extension run check`
- **Fix**: `make fix` runs Python fixes, `pi-extension` fixes, and `pi-swarm/extension` fixes/format commands

### Testing

- **Run all**: `make test` from repo root runs Python pytest plus the pi-extension and pi-swarm extension TypeScript checks/tests.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths = ["core/config/tests", "workspace/projects/tests", "pi-companion/tui/tests"]`, `pythonpath` includes `src`, `core/config/src`, `workspace/projects/src`, `pi-swarm/cli/src`, and `pi-companion/tui/src`.
- **TypeScript**: `npm --prefix pi-extension test` runs the session/state/project/workspace/git/workflow unit suites; `npm --prefix pi-swarm/extension test` currently validates the extension package skeleton.
- **Basecamp Python tests** live under `core/config/tests/`, `workspace/projects/tests/`, and `pi-companion/tui/tests/`.
