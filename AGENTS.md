# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

Root-level products:

| Product | Directory | Purpose |
|---------|-----------|---------|
| `basecamp` | `src/basecamp/` | Python composition CLI for setup/projects/install |
| `basecamp-core` | `core/config/` | Generic settings/files/paths/exceptions |
| `basecamp-workspace` | `workspace/projects/` | Project + per-repo environment config and interactive projects/environments menus |
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
├── src/basecamp_workspace/     # Project + environment config and interactive projects/environments menus
└── tests/                      # workspace pytest suite

pi-swarm/                      # Async-agent bounded context
├── protocol/                   # Protocol docs and frame fixtures
├── extension/                  # TypeScript Pi-side agent tools, launch policy, daemon client, reporter, /code-review
└── cli/                        # Python daemon CLI/runtime package

core/pi/                       # pi-core TypeScript package: registries, session, state, model aliases, workspace primitives
pi-ui/                         # Session UI package: footer, title, mode editor
workspace/pi/                  # pi-workspace TypeScript package: project context + workspace service
pi-tasks/                      # Tasks, planning, workflow skills
pi-git/                        # Prompt-only PR creation workflow (/create-pr)
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

### Session Modes

Agent modes (`core/pi`, in `SESSION_STATE_AGENT_MODES`) are `analysis`, `planning`, `copilot`, `supervisor`, and `executor`. shift+tab (`cycleAgentMode`) rotates only the cyclable modes — copilot is excluded from the cycle. `copilot` is a locked, launch-only mode: it is entered solely via `pi --copilot` (registered in `registerSession`, which forces copilot at `session_start` when the flag is present, else restores the stored mode) and is immutable — `cycleAgentMode` is a no-op in copilot, so shift+tab can neither enter nor leave it. `pi --copilot` takes precedence over `pi --workstream` (the workstream startup defers with a warning). Because Pi cannot unregister or per-session-gate a tool, `plan()` is removed from copilot by two layers keyed on `getAgentMode() === "copilot"`: a `tool_call` block in `pi-tasks` (the hard guarantee) and filtering the `plan` catalog item out of the copilot capabilities index in `workspace/pi` (with copilot.md carrying no plan() guidance). The `/plan` slash command is deprecated repo-wide; the `plan()` tool and `/show-plan` remain for non-copilot sessions.

### Pi Packages

Core public session/project/workspace/workflow/git/model-alias/capability/engineering behavior is split across pluggable Pi packages (`core/pi`, `workspace/pi`, `pi-ui`, `pi-tasks`, `pi-git`, `pi-bash-reviewer`, `pi-engineering`, `pi-companion/pi`). Async-agent protocol, Pi-side launch/tool behavior, and daemon runtime ownership live in the top-level `pi-swarm/` context.

### Code Review

`/code-review` (owned by `pi-swarm/extension`, in `src/agents/review/`) runs an independent third-party review of the current branch. The command dispatches six read-only reviewer agents (security, testing, docs, clarity, conventions, general) with a fixed scope-only brief, transposes each prose report into a canonical `Finding` schema via a per-report `fast`-model pass (forced `report_findings` tool, faithful extraction only), then merges findings and computes a verdict deterministically (no LLM synthesis). The primary agent triggers the command and receives the findings as the reviewee — it never authors or synthesizes the review. It is manual only. This replaces the removed `review_packet` / `code-walkthrough` surfaces and the old primary-agent `code-review` skill.

### Model Aliases

Model alias resolution is owned by `core/pi/src/model-aliases`, backed by `~/.pi/basecamp/core/model-aliases.json` with schema `{ "version": 1, "aliases": { "fast": "claude-haiku-4-5" } }`. `core/pi/src/platform/model-aliases.ts` is only the provider seam; it must not read config, define aliases, or own model-selection policy.

### Process-Scoped Singletons

Mutable state shared across Pi packages or required to survive `/reload` must live on `globalThis` behind a `Symbol.for("basecamp.*")` key, never a module-level `let`. On `/reload`, Pi re-imports every extension with fresh module instances (`moduleCache: false`), so each extension can hold its own copy of a shared module; only `globalThis`-backed state stays process-scoped and reload-stable. State read inside a `session_start` handler must initialize defensively (e.g. `ensureCurrentSessionStateForEvent`) rather than assuming another extension's `session_start` ran first — cross-extension handler ordering is not guaranteed and changes on reload. See `core/pi/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. For repo-backed sessions, `BASECAMP_REPO` is the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename when there is no parseable origin); for non-repo launches it falls back to the scratch-directory basename. It is never a worktree label. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are the active worktree's absolute path and label, or empty strings when no worktree is active.

The worktree setup hook (the per-repo `environments` `setup` command in `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity and run by `pi-tasks` on creation of a new execution worktree) additionally exposes `BASECAMP_REPO_ROOT` (the protected checkout path) to the setup command for the duration of that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live in `~/.worktrees/<org>/<name>/<label>/` (the per-repo root is the canonical `<org>/<name>` identity) rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, recognizes a session launched inside a linked worktree as its active worktree (setting the protected root to the main checkout and populating `BASECAMP_WORKTREE_DIR`/`LABEL`, without requiring a clean/default-branch main checkout), approved implementation plans activate a worktree inside the Pi session (workstream sessions reuse the already-active worktree instead of prompting), resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume. Worktree labels are either a direct label or a two-level `namespace/name`: plan-approved worktrees use `wt-<user-prefix>/<slug>`, while copilot-dispatched workstreams (`launch_workstream`) use a generic `copilot/<three-words>` label whose three words are also the launch id, paired with a work-derived `<user-prefix>/<slug>` (e.g. `bt/…`) branch.

The worktree root follows the canonical identity. Worktrees created under the legacy bare-name root (`~/.worktrees/<repo>/`) are migrated automatically: on primary (non-subagent) session start, Basecamp relocates the current repo's legacy worktrees to the `<org>/<name>` root via `git worktree move` (retrying dirty trees with `--force`, skipping locked ones). The main checkout, the session's own active worktree, and already-migrated trees are left untouched. Migration is best-effort — any per-worktree failure is skipped and never blocks session start, with a quiet notification only when something is moved or skipped. A resumed session whose previously active worktree was legacy reconnects after one `/worktree <label>`, since saved affinity still references the pre-migration identity.

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
