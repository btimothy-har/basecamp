# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

The repo is organized by the artifacts it ships (design record: docs/design/repo-rearchitecture.md):

| Product | Directory | Purpose |
|---------|-----------|---------|
| Basecamp Pi extension | `pi/` (`pi/extension.ts` + `pi/<domain>/`) | The single Pi package, registered from the repo root: all session, workspace, workflow, and agent behavior, assembled from domain modules |
| `basecamp` Python distribution | `src/basecamp/` | One ordinary src-layout package: CLI/installer shell plus the `basecamp.core`, `basecamp.workspace`, `basecamp.hub` (daemon), and `basecamp.companion` (TUI) subpackages |
| Claude extension *(reserved)* | `claude/` | A future Claude Code launcher (intent/README only for now) |

## Repo Map

```
package.json  tsconfig.json  biome.json   # THE TypeScript toolchain — repo root is the Pi package
pyproject.toml  uv.lock  install.py  Makefile   # Python toolchain + bootstrap
scripts/check-boundaries.ts                # Import-boundary lint (cross-domain via #<domain>/index.ts only)
scripts/check-file-length.ts               # Hard file-length caps: .ts ≤ 350, .py ≤ 500 (no exceptions)

pi/                            # ① the Pi extension (TypeScript)
├── extension.ts                # Composition root: registers all domain modules in fixed order (core first)
├── core/                       # agent-mode/ (+copilot·toggle) · session/ (+state) · project/ (config·context·injection·logseq · workspace/ runtime+guards+/worktree) ·
│                               #   git/ (worktrees/ crud·target·migrate · repo · /create-pr) · skills/ · catalog/ · model/ · ui/ (framework chrome) · escalate/ (+dialog/) · host/ (env·exec·paths·config) ·
│                               #   hub/ (hub-daemon connector: protocol/ TS↔Python contract · connection · ensure · identity · status · report-thread) ·
│                               #   swarm/ (the agent-dispatch primitive: agents/ = tools·catalog·launch·hub client·reporter·widget·observability·skills) · global-registry.ts
├── system-prompt/              # before_agent_start prompt assembly: prompt.ts · context-builders.ts · defaults/ (modes·styles·environment)
├── code-review/                # /code-review feature domain (findings·transpose·synthesis·orchestrate·command) over #core/swarm
├── workstreams/                # durable repo-neutral workstream coordination (create·edit·launch·list·status·start·herdr) over #core/swarm
├── companion/                  # dashboard integration (pure consumer): snapshot/, panes/, herdr/ + tmux/ adapters
├── tasks/                      # layered: schemas/ · lifecycle/ (state) · workflows/ (draft·review·handoff) · tools/ (task-tools·plan·guards·commands); skills/
├── bash-reviewer/              # LLM bash reviewer: index (guard), review, triage/, llm adapter
├── engineering/                # bigquery/ (bq_query tool + bq-CLI adapter, one module), skills/ + prompts/
└── browser/                    # primary-only browser automation: pinned Playwright CLI shim + on-demand skill

src/basecamp/                  # ② the basecamp Python package (one ordinary src-layout package)
├── cli.py                      # Click entry point (setup, projects, environments, companion, hub)
├── setup.py  installer.py      # environment setup + install orchestration (uv tool + npm + single pi install)
├── core/                       # settings, paths, files, exceptions + unified config.json: validation registry (config_schema) · generic get/set/edit (config_document) · `basecamp config` CLI (plumbing + project/env/alias porcelain)
├── workspace/                  # per-repo worktree-setup environments + menus
├── hub/                         # the daemon (host-global service): core (app·server·http_routes·registry) + frames/ + store/ (per data object) + swarm/ (agents) + broker/ (companion analysis)
└── companion/                   # Textual TUI (ui/) + daemon observability client; analysis is daemon-sourced (raw thread reported by core/hub)

claude/                        # ③ reserved for a future Claude Code launcher
docs/  tests/  migrations/     # design docs; Python tests (tests/<domain>/); one-shot state migration
```

`basecamp` is one ordinary src-layout package under `src/basecamp/` — `import basecamp.<domain>` resolves to `src/basecamp/<domain>/`. (The pre-rearchitecture PEP 420 namespace-portion layout, with per-domain `py/` roots and a `check-namespace` guard, is gone.)

Cross-domain TypeScript imports use Node subpath imports (`#core/*` freely; other domains only via `#<domain>/index.ts`; core imports no other domain), enforced by `scripts/check-boundaries.ts` in `npm run check`.

## Architecture Decisions

### Prompt System

The system prompt is fully replaced, not appended. This gives complete control over the agent's behavior but means basecamp must provide everything pi's default prompt would (environment context, tool guidance, etc.). Pi's tool definitions and skill listings are sourced dynamically via `getAllTools()`/`getCommands()` and included in the assembled prompt.

Prompts are layered (environment → working style → project context → tools/skills) so that each concern is independently overridable. Project context is assembled directly into the system prompt alongside all other layers.

### Browser Automation

`pi/browser/` exposes no custom browser tools. Primary sessions discover the Basecamp-owned `playwright-cli` skill on demand and receive one private PATH entry containing only a gated shim for the exact-pinned `@playwright/cli`; subagents receive neither, and direct shim execution rejects `BASECAMP_AGENT_DEPTH > 0`. The shim defaults to a headed persistent Playwright session using system Chrome (Brave fallback on macOS), honors `BASECAMP_BROWSER_PATH` and explicit `PLAYWRIGHT_MCP_*` overrides, blocks installation commands, and routes auto-named artifacts to the private bounded `~/.pi/basecamp/browser/playwright-output` directory. Screenshots are inspected with `read` after the CLI writes the PNG.

Playwright owns a fresh managed persistent profile. The retired `~/.pi/basecamp/browser/profile` and any legacy Chrome/CDP process are never migrated, modified, or terminated by Basecamp.

### Session Modes

Agent modes (`pi/core/agent-mode`, in `SESSION_STATE_AGENT_MODES`) are `analysis`, `planning`, `work`, and `copilot`. `work` is the default — the working posture where the primary session implements directly; `analysis` and `planning` are read-only / pre-implementation postures. shift+tab (`cycleAgentMode`) rotates only the cyclable modes (`analysis`, `planning`, `work`) — copilot is excluded from the cycle. Approving an implementation plan hands off to `work` mode (the old supervisor-vs-IC/executor choice is gone); analysis plans stay in `analysis`. `copilot` is a locked, launch-only mode: it is entered solely via `pi --copilot` (registered in `registerSession`, which forces copilot at `session_start` when the flag is present, else restores the stored mode) and is immutable — `cycleAgentMode` is a no-op in copilot, so shift+tab can neither enter nor leave it. `pi --copilot` takes precedence over `pi --workstream` (the workstream startup defers with a warning). Because Pi cannot unregister or per-session-gate a tool, `plan()` is removed from copilot by two layers sharing one predicate (`isCopilotMode` in `pi/core/agent-mode`, paired with `PLAN_TOOL_NAME` — `plan()` is a Pi built-in, so its name is a core-owned constant beside the mode policy, not a tasks export): the tasks module's `tool_call` block (the hard guarantee) and the workspace module's copilot capabilities-index filter (with copilot.md carrying no plan() guidance). The `/plan` slash command is deprecated repo-wide; the `plan()` tool and `/show-plan` remain for non-copilot sessions.

### Agent Execution Posture

Dispatched agents default to **read-only** — `AgentConfig.readOnly` is fail-closed (read-only unless a persona sets `readOnly: false`): `getAgentToolAllowlist()` (`pi/core/swarm/agents/types.ts`) yields a toolset without `write`/`edit`, they launch `--read-only`, and they share the parent's worktree (seeing its live WIP). A **mutative** agent (currently only `worker`) instead gets its **own git worktree** — `agent-<runToken>/<name>`, branched from the parent worktree's HEAD and keyed per-run so re-tasks don't collide (`pi/core/swarm/agents/mutative-worktree.ts` over the `pi/core/git/worktrees/lifecycle.ts` primitives). It spawns with `cwd` = that worktree (auto-adopted via `isLinkedWorktree`), gets `write`/`edit` (`getMutativeAgentToolAllowlist()`), is confined to that worktree by the workspace guard's `allowed_dirs` rule (`pi/core/project/workspace/guards.ts`), and commits its work to a branch — the branch is the deliverable, the **primary integrates it by merge** and the worktree is torn down on finish (the branch is kept for the parent to merge, then deleted). `bash` is retained (scouts need `git log`/`gh`, reviewers need `git diff`) and is deliberately **not** a mutation sandbox — a bash write can still reach the filesystem, so toolset + worktree confinement is defense-in-depth, not a wall; the symmetric bash-reviewer `allowed_dirs` pass is the next increment. The full design is `docs/design/agent-isolation.md`. Independently, the workspace `tool_call` guard hard-blocks structured `write`/`edit` to the protected main checkout even when a subagent has no active worktree.

### Extension Modules

All TypeScript behavior ships as one Pi extension; its entry point is `pi/extension.ts` and its package manifest is the repo-root `package.json`. `pi/extension.ts` composes the domain modules (`core`, `system-prompt`, `tasks`, `bash-reviewer`, `engineering`, `browser`, `companion`, `code-review`, `workstreams`) in a fixed order — core first — so in-extension init is deterministic and identical on `/reload`. Each domain's TS lives in `pi/<domain>/` with a `register*` default export in its `index.ts`; cross-domain imports go through `#`-subpath aliases and are boundary-checked. Framework UI (footer/header/title/mode) is not a separate domain — it lives in `pi/core/ui/` and `registerCore` registers it, alongside core's other in-session surfaces (`escalate`, `skills`, the `project` runtime — config + `workspace/` + context — and `git`'s `/create-pr`). Git worktree/repo mechanics live in `pi/core/git/` and are imported directly. The hub-daemon connector — the WebSocket transport, the wire protocol (`protocol/`), ensure-daemon, node identity, and the raw-thread reporter — lives in `pi/core/hub/` (core's adapter for the hub daemon, a peer of `git`/`host`/`model`). Every top-level session and daemon-spawned agent connects through it, and `registerCore` also registers the reporter, so "connect + report" is one core responsibility: each session ships its raw thread to the daemon at `agent_end`, and the daemon derives the analysis. The **agent-dispatch primitive** (dispatch/ask/cancel/peer tools, run reporter, active-agents widget, agent catalog) is a second core adapter, `pi/core/swarm/` (`#core/swarm`), registered by `registerCore` right after the hub connector — substrate rather than a feature, since multiple domains build on it. `pi/code-review/` (the `/code-review` command) and `pi/workstreams/` (durable coordination state) are standalone feature domains that consume the primitive via `#core/swarm`; `pi/companion/` is a pure downstream consumer of the derived analysis (dashboard integration — snapshot/panes/herdr — with no `#core/hub` dependency). The Python daemon is `src/basecamp/hub/` (its `hub/swarm/` service is the server side of the primitive; the on-disk runtime path stays `~/.pi/basecamp/swarm/`).

### Code Review

`/code-review` (owned by the `code-review` domain, in `pi/code-review/`, over the `#core/swarm` primitive) runs an independent third-party review of the current branch. The command dispatches six read-only reviewer agents (security, testing, docs, clarity, conventions, general) with a fixed scope-only brief, transposes each prose report into a canonical `Finding` schema via a per-report `fast`-model pass (forced `report_findings` tool, faithful extraction only), then merges findings and computes a verdict deterministically (no LLM synthesis). The primary agent triggers the command and receives the findings as the reviewee — it never authors or synthesizes the review. It is manual only. This replaces the removed `review_packet` / `code-walkthrough` surfaces and the old primary-agent `code-review` skill.

### Model Aliases

Model alias resolution is owned by `pi/core/model` — `model/index.ts` is the provider seam plus the native config-backed provider, `model/aliases.ts` is the read-side config IO, and `model/resolution.ts` is the string→Model plumbing (reasoning-effort, tool-choice) — backed by the `model_aliases` section of the unified `~/.pi/basecamp/config.json` (`{ "fast": "claude-haiku-4-5" }`). Pi reads the section **in-process**; Basecamp (Python) is the **sole config writer**, so the `/model-aliases` TUI persists each change by shelling out to `basecamp config alias set|remove` (the same file the CLI's flock'd `Settings` guards). The seam itself owns no config or policy; the native provider reads `model/aliases.ts`.

### State: wiring vs. surviving

Two kinds of module state, two rules. **Wiring** (providers/registries the composition root re-establishes on every load — cwd provider, catalog, model aliases, workspace allowed-roots) is plain module state. **Surviving state** (live session data that must outlive `/reload`, which re-imports the extension with fresh module instances — session state, agent mode, invoked skills, workspace runtime, daemon WebSocket) uses `processScoped(key, init)` from `pi/core/global-registry.ts`; key strings are stable across releases. Default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session. Init order is deterministic (core registers first in `extension.ts`), so later modules may assume core-owned state is initialized. See `pi/core/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` env vars on `process.env`. Subagents spawned via the `agent` tool inherit these automatically as child processes.

Relevant vars include `BASECAMP_PROJECT`, `BASECAMP_REPO`, `BASECAMP_SCRATCH_DIR`, `BASECAMP_WORKTREE_DIR`, and `BASECAMP_WORKTREE_LABEL`. For repo-backed sessions, `BASECAMP_REPO` is the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename when there is no parseable origin); for non-repo launches it falls back to the scratch-directory basename. It is never a worktree label. `BASECAMP_WORKTREE_DIR` and `BASECAMP_WORKTREE_LABEL` are the active worktree's absolute path and label, or empty strings when no worktree is active. `BASECAMP_USER_FACING` is stamped `0` by the daemon on backgrounded workers (absent ⇒ user-facing); the hub node identity derives the node's `role` — `agent` (user-facing) vs `worker` (backgrounded) — from it, and records `BASECAMP_REPO` / `BASECAMP_WORKTREE_LABEL` as first-class identity facets on the daemon `agents` row.

The worktree setup hook (the per-repo `environments` `setup` command in `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity and run by the `tasks` module on creation of a new execution worktree) additionally exposes `BASECAMP_REPO_ROOT` (the protected checkout path) to the setup command for the duration of that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live in `~/.worktrees/<org>/<name>/<label>/` (the per-repo root is the canonical `<org>/<name>` identity) rather than inside the repo to avoid polluting project directories. Git is the source of truth for worktree registration (`git worktree list --porcelain`); Basecamp does not maintain a parallel metadata registry. Sessions are launched with plain `pi` from a repository or subdirectory; Basecamp detects the configured repo root, recognizes a session launched inside a linked worktree as its active worktree (setting the protected root to the main checkout and populating `BASECAMP_WORKTREE_DIR`/`LABEL`, without requiring a clean/default-branch main checkout), approved implementation plans activate a worktree inside the Pi session (workstream sessions reuse the already-active worktree instead of prompting), resumed/reloaded/forked sessions restore their last active worktree when still in the same repo, and `/worktree [label]` can switch to an existing Git-registered worktree after session resume. Worktree labels are either a direct label or a two-level `namespace/name`: plan-approved worktrees use `wt-<user-prefix>/<slug>`, while copilot-dispatched workstreams (`launch_workstream`) use a generic `copilot/<slug>` label whose three-word slug is the workstream's readable id, paired with a work-derived `<user-prefix>/<slug>` (e.g. `bt/…`) branch.

The worktree root follows the canonical identity. Worktrees created under the legacy bare-name root (`~/.worktrees/<repo>/`) are migrated automatically: on primary (non-subagent) session start, Basecamp relocates the current repo's legacy worktrees to the `<org>/<name>` root via `git worktree move` (retrying dirty trees with `--force`, skipping locked ones). The main checkout, the session's own active worktree, and already-migrated trees are left untouched. Migration is best-effort — any per-worktree failure is skipped and never blocks session start, with a quiet notification only when something is moved or skipped. A resumed session whose previously active worktree was legacy reconnects after one `/worktree <label>`, since saved affinity still references the pre-migration identity.

### Workstreams

Workstreams are durable, repo-neutral internal coordination state owned by the `workstreams` domain (`pi/workstreams/`, over the `#core/swarm` primitive). Persistence is the daemon's SQLite store (`~/.pi/basecamp/swarm/daemon.db`, tables `workstreams`, `workstream_versions`, and `workstream_agents`, beside `agents`/`runs`) — the former JSON launch-index is gone (clean break, no migration). Identity is an internal `ws_<uuid>` id plus a globally-unique three-word readable `slug`. Content (`label`/`brief`/`constraints`) is versioned: the `workstreams` row carries the current `version` and each version is snapshotted in `workstream_versions` (append-only history). Worktrees are NOT persisted — git remains the source of truth; the `copilot/<slug>` worktree name encodes the slug.

The model is multi-agent and repo-neutral: every `pi --workstream` session appends a `workstream_agents` row (additive, concurrent, never overwrites), and "which repos touched" derives from agent rows. Record shaping and execution staging are decoupled: `create_workstream`/`edit_workstream` manage the durable record, `launch_workstream` provisions the worktree + pane for an existing workstream (and can launch it into a different repo for cross-repo coordination without a duplicate). The dossier (Logseq work page, `work__<org>__<repo>__<slug>`) stays the user-facing durable record of priority, decisions, blockers, and done signals; the workstream points to it via `source_dossier_path`. One dossier may have many workstreams.

The `pi --workstream` flag is boolean: bare `--workstream` infers the workstream from the current `copilot/<slug>` worktree label; `--workstream=<slug|id>` resolves explicitly (the value is recovered from argv). On start — **only on a genuinely fresh session** (the `session_start` handler no-ops when the conversation already has user/assistant turns, so resume/reload/fork/compact never re-inject) — it attaches the session as an additive workstream agent and injects the latest brief. Tools are `create_workstream` (record-only: daemon record + slug, no worktree/pane), `edit_workstream` (revise content in place → new version, old version retained), `launch_workstream` (provision the `copilot/<slug>` worktree + Herdr pane for an existing workstream), `list_workstreams` (repo-neutral filtered listing; single-identifier lookup returns the joined agents view + version history), and `set_workstream_status` (open ↔ closed). Transport: protocol v22 WS frames (`create_workstream`/`attach_workstream_agent`/`update_workstream`/`revise_workstream` + acks) and HTTP GET `/workstreams` (filtered list) and `/workstreams/{id_or_slug}` (workstream + joined agents + version history).

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py` (installs the `basecamp` tool, then registers the repo root as the single Pi extension, cleaning up legacy per-package registrations)
- **Iterate on the CLI**: `uv run install.py` installs a **non-editable** snapshot of `basecamp` on PATH, so for live iteration against your working tree run the CLI via `uv run basecamp <cmd>` (the `uv sync` editable dev venv) rather than re-installing after each change
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `npm run check` at the repo root (tsc whole-graph + biome + import-boundary + file-length checks); `make lint` runs it after the Python checks
- **Fix**: `make fix` runs Python fixes plus `npm run lint:fix` / `npm run format`

### File Length Limits

Hard caps on every file, tests included: **TypeScript ≤ 350 lines, Python ≤ 500 lines**, enforced by `scripts/check-file-length.ts` in `npm run check` (and therefore `make lint` and CI).

The cap is a module-design forcing function. When a file approaches it, split along responsibility seams — named modules with one job each. Never satisfy the cap by compressing style (collapsing blank lines, one-lining logic), and never with `-part2`-style continuation files: if no seam is apparent, the file owns more than one responsibility and the design needs rethinking, not the formatting.

There are no per-file exceptions and no suppression mechanism. (Files that predated the rule were migrated through a shrink-only `GRANDFATHERED` ratchet, burned to zero in July 2026 and removed from the script — never reintroduce per-file exceptions.)

### Testing

- **Run all**: `make test` from repo root runs `uv run pytest` plus `npm test`.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths` is root `tests/`, with a subdir per domain (`tests/core/`, `tests/workspace/`, `tests/swarm/`, `tests/companion/`) beside the CLI-shell tests; imports resolve via the editable install (`uv sync`), no `pythonpath` stitching.
- **TypeScript**: `npm test` runs the Node test runner over every domain's `pi/<domain>/**/*.test.ts` (one child process per test file), plus `pi/extension.test.ts` (whole-graph load + registration under strict Node). A new domain's tests must be added to the `test` glob list in `package.json`.
- **Tests live beside their code**: `pi/<domain>/**/tests/` (TS) and `tests/<domain>/` (Python).

## Pull Requests

Open every PR **as a draft** and drive it to done in order — never skip a step or open one ready for review:

1. **Open in draft.** No PR starts ready for review.
2. **Get CI green.** Poll the PR's checks (`.github/workflows/ci.yml`) and fix whatever fails; do not proceed while CI is red.
3. **Mark ready once CI is green.** Flipping the PR out of draft is also what triggers `.github/workflows/claude-review.yml` (it skips drafts), so the reviewer only ever sees a green, ready PR.
4. **Clear the review.** Poll for the Claude review, fix every issue it raises, and reply to and/or resolve every review comment before treating the PR as done.
