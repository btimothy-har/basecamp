# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

> **Repo consolidation in progress** (docs/design/repo-consolidation.md): phase 1 (TypeScript) has landed — the repo root is now a single Pi extension assembled from paired contexts. Python packages consolidate in phase 3; this file gets its full rewrite in phase 4.

Root-level products:

| Product | Directory | Purpose |
|---------|-----------|---------|
| Basecamp Pi extension | repo root (`extension.ts` + `<context>/ts/`) | The single Pi package: all session, workspace, workflow, and agent behavior, assembled from context modules |
| `basecamp` | `src/basecamp/` | Python composition CLI for setup/projects/install |
| `basecamp-core` | `core/config/` | Generic settings/files/paths/exceptions (folds into `core/py` in phase 3) |
| `basecamp-workspace` | `workspace/projects/` | Project + per-repo environment config and menus (folds into `workspace/py` in phase 3) |
| `pi-swarm` daemon | `pi-swarm/cli/` | Python daemon CLI/runtime (folds into `swarm/py` in phase 3) |
| `companion-tui` | `pi-companion/tui/` | Python companion TUI/analyzer (folds into `companion/py` in phase 3) |

## Repo Map

```
package.json  tsconfig.json  biome.json   # THE TypeScript toolchain — repo root is the Pi package
extension.ts                               # Composition root: registers all context modules in fixed order
scripts/check-boundaries.ts                # Import-boundary lint (cross-context via #<context>/index.ts only)

core/                          # Bilingual context: foundation
├── ts/                         # registries, session lifecycle, state, model aliases, platform seams
└── config/                     # basecamp-core Python package (→ core/py in phase 3)

workspace/                     # Bilingual context: projects + worktrees
├── ts/                         # project context, prompt assembly, worktree service, guards
└── projects/                   # basecamp-workspace Python package (→ workspace/py in phase 3)

swarm/                         # Bilingual context: async agents
├── ts/                         # agent tools, launch policy, daemon client, /code-review, workstreams
├── protocol/                   # wire-protocol docs and frame fixtures (TS↔Python contract)
└── skills/                     # agents skill

companion/                     # Bilingual context: companion
└── ts/                         # session hooks, tmux panes, analysis registration
pi-companion/tui/               # Python companion TUI/analyzer (→ companion/py in phase 3)
pi-swarm/cli/                   # Python swarm daemon (→ swarm/py in phase 3)

ui/ts/                         # Session UI: footer, title, mode editor
tasks/                         # Tasks + planning: ts/ + skills/
git/ts/                        # Prompt-only PR creation workflow (/create-pr)
bash-reviewer/ts/              # LLM bash reviewer: gates risky git/gh/shell commands
engineering/                   # Engineering: ts/ + skills/ + prompts/
browser/ts/                    # Browser automation tools (puppeteer-core over CDP)

src/basecamp/                  # Root Python composition package
├── cli.py                      # Click entry point (setup, projects, install, companion)
├── setup.py                    # Environment setup (prerequisites, scaffolding)
└── installer.py                # Install orchestration: uv tool + npm install + single `pi install`
```

Cross-context TypeScript imports use Node subpath imports (`#core/*` freely; other contexts only via `#<context>/index.ts`), enforced by `scripts/check-boundaries.ts` in `npm run check`.

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Session Modes

Agent modes (`core/ts`, in `SESSION_STATE_AGENT_MODES`) are `analysis`, `planning`, `copilot`, `supervisor`, and `executor`. shift+tab (`cycleAgentMode`) rotates only the cyclable modes — copilot is excluded from the cycle. `copilot` is a locked, launch-only mode: it is entered solely via `pi --copilot` (registered in `registerSession`, which forces copilot at `session_start` when the flag is present, else restores the stored mode) and is immutable — `cycleAgentMode` is a no-op in copilot, so shift+tab can neither enter nor leave it. `pi --copilot` takes precedence over `pi --workstream` (the workstream startup defers with a warning). Because Pi cannot unregister or per-session-gate a tool, `plan()` is removed from copilot by two layers keyed on `getAgentMode() === "copilot"`: a `tool_call` block in `pi-tasks` (the hard guarantee) and filtering the `plan` catalog item out of the copilot capabilities index in `workspace/pi` (with copilot.md carrying no plan() guidance). The `/plan` slash command is deprecated repo-wide; the `plan()` tool and `/show-plan` remain for non-copilot sessions.

### Extension Modules

All TypeScript behavior ships as one Pi extension registered from the repo root. `extension.ts` composes the context modules (`core`, `ui`, `workspace`, `tasks`, `git`, `bash-reviewer`, `engineering`, `browser`, `companion`, `swarm`) in a fixed order — core first — so in-extension init is deterministic and identical on `/reload`. Each context's TS lives in `<context>/ts/` with a `register*` default export in its `index.ts`; cross-context imports go through `#`-subpath aliases and are boundary-checked. Async-agent protocol and daemon runtime live in the `swarm/` context (daemon Python still at `pi-swarm/cli/` until phase 3).

### Code Review

`/code-review` (owned by the `swarm` context, in `swarm/ts/agents/review/`) runs an independent third-party review of the current branch. The command dispatches six read-only reviewer agents (security, testing, docs, clarity, conventions, general) with a fixed scope-only brief, transposes each prose report into a canonical `Finding` schema via a per-report `fast`-model pass (forced `report_findings` tool, faithful extraction only), then merges findings and computes a verdict deterministically (no LLM synthesis). The primary agent triggers the command and receives the findings as the reviewee — it never authors or synthesizes the review. It is manual only. This replaces the removed `review_packet` / `code-walkthrough` surfaces and the old primary-agent `code-review` skill.

### Model Aliases

Model alias resolution is owned by `core/ts/model-aliases`, backed by `~/.pi/basecamp/core/model-aliases.json` with schema `{ "version": 1, "aliases": { "fast": "claude-haiku-4-5" } }`. `core/ts/platform/model-aliases.ts` is only the provider seam; it must not read config, define aliases, or own model-selection policy.

### Process-Scoped Singletons

Mutable state shared across Pi packages or required to survive `/reload` must live on `globalThis` behind a `Symbol.for("basecamp.*")` key, never a module-level `let`. On `/reload`, Pi re-imports every extension with fresh module instances (`moduleCache: false`), so each extension can hold its own copy of a shared module; only `globalThis`-backed state stays process-scoped and reload-stable. State read inside a `session_start` handler must initialize defensively (e.g. `ensureCurrentSessionStateForEvent`) rather than assuming another extension's `session_start` ran first — cross-extension handler ordering is not guaranteed and changes on reload. See `core/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. For repo-backed sessions, `BASECAMP_REPO` is the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename when there is no parseable origin); for non-repo launches it falls back to the scratch-directory basename. It is never a worktree label. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are the active worktree's absolute path and label, or empty strings when no worktree is active.

The worktree setup hook (the per-repo `environments` `setup` command in `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity and run by the `tasks` module on creation of a new execution worktree) additionally exposes `BASECAMP_REPO_ROOT` (the protected checkout path) to the setup command for the duration of that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live in `~/.worktrees/<org>/<name>/<label>/` (the per-repo root is the canonical `<org>/<name>` identity) rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, recognizes a session launched inside a linked worktree as its active worktree (setting the protected root to the main checkout and populating `BASECAMP_WORKTREE_DIR`/`LABEL`, without requiring a clean/default-branch main checkout), approved implementation plans activate a worktree inside the Pi session (workstream sessions reuse the already-active worktree instead of prompting), resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume. Worktree labels are either a direct label or a two-level `namespace/name`: plan-approved worktrees use `wt-<user-prefix>/<slug>`, while copilot-dispatched workstreams (`launch_workstream`) use a generic `copilot/<slug>` label whose three-word slug is the workstream's readable id, paired with a work-derived `<user-prefix>/<slug>` (e.g. `bt/…`) branch.

The worktree root follows the canonical identity. Worktrees created under the legacy bare-name root (`~/.worktrees/<repo>/`) are migrated automatically: on primary (non-subagent) session start, Basecamp relocates the current repo's legacy worktrees to the `<org>/<name>` root via `git worktree move` (retrying dirty trees with `--force`, skipping locked ones). The main checkout, the session's own active worktree, and already-migrated trees are left untouched. Migration is best-effort — any per-worktree failure is skipped and never blocks session start, with a quiet notification only when something is moved or skipped. A resumed session whose previously active worktree was legacy reconnects after one `/worktree <label>`, since saved affinity still references the pre-migration identity.

### Workstreams

Workstreams are durable, repo-neutral internal coordination state owned by the `swarm` context (`swarm/ts/workstreams/`). Persistence is the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams` and `workstream_agents`, beside `agents`/`runs`) — the former JSON launch-index is gone (clean break, no migration). Identity is an internal `ws_<uuid>` id plus a globally-unique three-word readable `slug`. Worktrees are NOT persisted — git remains the source of truth; the `copilot/<slug>` worktree name encodes the slug.

The model is multi-agent and repo-neutral: every `pi --workstream` session appends a `workstream_agents` row (additive, concurrent, never overwrites), and "which repos touched" derives from agent rows. A workstream can be carried into a different repo by passing its id/slug to `launch_workstream`, enabling cross-repo coordination without a duplicate workstream. The dossier (Logseq work page, `work__<org>__<repo>__<slug>`) stays the user-facing durable record of priority, decisions, blockers, and done signals; the workstream points to it via `source_dossier_path`. One dossier may have many workstreams.

The `pi --workstream` flag is boolean: bare `--workstream` infers the workstream from the current `copilot/<slug>` worktree label; `--workstream=<slug|id>` resolves explicitly (the value is recovered from argv). On start it attaches the session as an additive workstream agent and injects the brief. Tools are `launch_workstream` (create + worktree + Herdr, or carry existing), `list_workstreams` (repo-neutral filtered listing; single-identifier lookup returns the joined agents view), and `set_workstream_status` (open ↔ closed). Transport: protocol v19 WS frames (`create_workstream`/`attach_workstream_agent`/`update_workstream` + acks) and HTTP GET `/workstreams` (filtered list) and `/workstreams/{id_or_slug}` (workstream + joined agents).

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py -e` (editable mode; installs `basecamp` with all extras, then registers the repo root as the single Pi extension, cleaning up legacy per-package registrations)
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `npm run check` at the repo root (tsc whole-graph + biome + import-boundary check); `make lint` runs it after the Python checks
- **Fix**: `make fix` runs Python fixes plus `npm run lint:fix` / `npm run format`

### Testing

- **Run all**: `make test` from repo root runs `uv run pytest` plus `npm test`.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths` covers root `tests/` plus the Python package test dirs; `pythonpath` includes `src`, `core/config/src`, `workspace/projects/src`, `pi-swarm/cli/src`, and `pi-companion/tui/src` (retired in phase 3).
- **TypeScript**: `npm test` runs the Node test runner over every context's `ts/**/*.test.ts` in one process.
- **TS tests live beside their code** in `<context>/ts/**/tests/`; Python package tests remain under `core/config/tests/`, `workspace/projects/tests/`, `pi-swarm/cli/tests/`, and `pi-companion/tui/tests/`.
