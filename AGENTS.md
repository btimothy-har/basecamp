# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

The repo is organized by the artifacts it ships:

| Product | Directory | Purpose |
|---------|-----------|---------|
| Basecamp Pi extension | `pi/` (`pi/extension.ts` + `pi/<domain>/`) | The single Pi package, registered from the repo root: all session, workspace, workflow, and agent behavior, assembled from domain modules |
| `basecamp` Python distribution | `src/basecamp/` | One ordinary src-layout package: CLI/installer shell plus the `basecamp.core`, `basecamp.workspace`, `basecamp.hub` (daemon), and `basecamp.companion` (TUI) subpackages |

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
├── code-review/                # /skill:code-review feature domain (user-invoked skill + report_findings tool: findings·synthesis·annotate-pane·artifact)
├── workstreams/                # durable repo-neutral workstream coordination (create·edit·launch·list·status·start·herdr) over #core/swarm
├── companion/                  # dashboard integration (pure consumer): snapshot/, panes/, herdr/ + tmux/ adapters
├── tasks/                      # layered: schemas/ · lifecycle/ (state) · workflows/ (draft·review·handoff) · tools/ (task-tools·plan·guards·commands); skills/
├── bash-reviewer/              # LLM bash reviewer: index (guard), review, triage/, llm adapter
├── engineering/                # bigquery/ (bq_query tool + bq-CLI adapter, one module), skills/ + prompts/
└── browser/                    # primary-only browser automation: pinned Playwright CLI shim + on-demand skill

src/basecamp/                  # ② the basecamp Python package (one ordinary src-layout package)
├── cli.py                      # Click entry point (config, setup, doctor, install, companion, hub)
├── setup.py  installer.py      # environment setup + install orchestration (uv tool + npm + single pi install)
├── config_cli/                 # `basecamp config` CLI shell (plumbing + project/env/alias porcelain); composition layer over core + workspace, so it lives beside cli.py (core imports no other domain)
├── core/                       # settings/ package (store = locked config.json primitive · schema = section registry · document = generic get/set/edit) + models (config record types: project/env/logseq) + paths (the ~/.pi/basecamp tree, incl. the swarm/companion runtime layout) · console (the shared rich pair) · files · exceptions · doctor
├── workspace/                  # per-repo worktree-setup environments + menus
├── hub/                         # the daemon (host-global service): core (app·server·http_routes·registry) + frames/ + store/ (per data object) + swarm/ (agents) + broker/ (companion analysis)
└── companion/                   # Textual TUI (ui/) + daemon observability client; analysis is daemon-sourced (raw thread reported by core/hub)

tests/  migrations/            # Python tests (tests/<domain>/); one-shot state migration
```

`basecamp` is one ordinary src-layout package under `src/basecamp/` — `import basecamp.<domain>` resolves to `src/basecamp/<domain>/`. (The pre-rearchitecture PEP 420 namespace-portion layout, with per-domain `py/` roots and a `check-namespace` guard, is gone.)

Cross-domain TypeScript imports use Node subpath imports (`#core/*` freely; other domains only via `#<domain>/index.ts`; core imports no other domain), enforced by `scripts/check-boundaries.ts` in `npm run check`.

## Documentation

Documentation lives in exactly two files — there is no `docs/` tree:

- **`README.md`** — anything user-facing.
- **`AGENTS.md`** (this file) — anything agent-facing that isn't obvious from the code: architecture decisions, cross-cutting conventions, and rationale a reader can't reconstruct from the source alone.

Do **not** create design or plan documents. Planning happens through the `plan()` tool and the plan is handed to the implementer, not written to a file. Most changes need no prose at all — the code and its tests are the record. When something durable is worth writing down, it goes in one of these two files.

## Architecture Decisions

### Prompt System

The system prompt is fully **replaced**, not appended — this buys complete control but obliges basecamp to supply everything pi's default prompt would (environment context, tool/skill listings, etc.), so pi's tool and command listings are sourced dynamically rather than assumed. The layers (environment → working style → project context → tools/skills) keep each concern independently overridable.

### Browser Automation

`pi/browser/` exposes no custom browser tools and is **primary-only**: a top-level session discovers the `playwright-cli` skill on demand and gets one private PATH entry — a gated shim for the exact-pinned `@playwright/cli`. Subagents get neither, and the shim rejects `BASECAMP_AGENT_DEPTH > 0`. The shim blocks install commands and confines artifacts to a bounded private directory.

Playwright owns a fresh managed profile. The retired `~/.pi/basecamp/browser/profile` and any legacy Chrome/CDP process are never migrated, modified, or terminated in normal operation. The sole exception is `basecamp doctor --clean`, which may reclaim the retired profile only when it is **provably unused** — superseded, unlocked (its Chrome `SingletonLock` names no live pid), and cold (past the staleness threshold) — and only after explicit user confirmation. It never touches a live process or a held/warm profile.

### Session Modes

Agent modes are `analysis`, `planning`, `work`, and `copilot`. `work` is the default (the primary implements directly); `analysis` and `planning` are read-only / pre-implementation postures. shift+tab cycles only `analysis`/`planning`/`work` — approving an implementation plan hands off to `work`, while analysis plans stay in `analysis`. `copilot` is a locked, launch-only mode: entered solely via `pi --copilot`, immutable (shift+tab is a no-op, so it can neither enter nor leave it), and it takes precedence over `pi --workstream`. Because Pi cannot unregister or per-session-gate a tool, `plan()` is kept out of copilot by two independent layers sharing one predicate — a hard `tool_call` block plus a capabilities-index filter — rather than a single gate. The `/plan` slash command is deprecated repo-wide; `plan()` and `/show-plan` remain for non-copilot sessions.

### Agent Execution Posture

Dispatched agents default to **read-only**, fail-closed (read-only unless a persona sets `readOnly: false`): they get a toolset without `write`/`edit`, launch `--read-only`, and share the parent's worktree so they see its live WIP. A **mutative** agent (currently only `worker`) instead gets its **own git worktree**, branched from the parent's HEAD and keyed per-run so re-tasks don't collide; it commits to a branch that the **primary integrates by merge**. Worker worktrees are atomically locked while live, and the daemon removes them on finish only when clean; a dirty residual stays recoverable, while the session-start sweep skips locks and never force-removes post-execution work. The Git lock is a cleanup/liveness guard, not a mutation lease. Mutating sessions with active dirty worktrees receive one hidden, advisory commit reminder before settling. The worktree is the isolation boundary, enforced by the workspace guard's `allowed_dirs` rule. `bash` is deliberately retained (scouts need `git log`, reviewers need `git diff`) and is **not** a mutation sandbox — a bash write still reaches the filesystem, so toolset + worktree confinement is defense-in-depth, not a wall. Independently, the workspace `tool_call` guard hard-blocks structured `write`/`edit` to the protected main checkout even when a subagent has no active worktree.

### Extension Modules

All TypeScript ships as **one** Pi extension (`pi/extension.ts`; manifest = the repo-root `package.json`). It composes the domain modules in a **fixed order, core first**, so init is deterministic and identical on `/reload`. Each domain exposes a `register*` default export; cross-domain imports go only through `#`-subpath aliases and are boundary-checked (core imports no other domain).

Core owns the substrate the other domains build on: framework UI (`pi/core/ui/`, not its own domain), git/worktree mechanics (`pi/core/git/`), the hub-daemon connector (`pi/core/hub/` — every session connects through it and ships its raw thread at `agent_end`, so "connect + report" is one core responsibility), and the **agent-dispatch primitive** (`pi/core/swarm/`, `#core/swarm` — a primitive rather than a feature, because multiple domains dispatch agents). The feature domains ride on that substrate: `code-review` and `workstreams` consume `#core/swarm`, and `companion` is a pure downstream consumer of the derived analysis (no `#core/hub` dependency). The Python daemon is `src/basecamp/hub/`.

### Code Review

`/skill:code-review` runs an **independent** third-party review of the current branch. It is a user-invoked skill (`disable-model-invocation` — hidden from the model, primary-only). The session dispatches read-only reviewer specialists, transposes their reports into the `Finding` schema, and calls `report_findings`, which merges the findings and computes the verdict **deterministically** — no LLM synthesis, and the verdict ignores the reviewee's opinion. The top-level session is the reviewee: it orchestrates and relays but never decides the verdict, carries every finding through verbatim, and may attach a `response` to contest one but never drops or softens it. Reviewer independence lives in the persona prompts, not an orchestration boundary. Manual only.

### Model Aliases

Model-alias resolution is owned by `pi/core/model`, backed by the `model_aliases` section of the unified `~/.pi/basecamp/config.json`. Pi reads it **in-process**, but Basecamp (Python) is the **sole config writer** — so the `/model-aliases` TUI persists each change by shelling out to `basecamp config alias set|remove` (the same flock'd `Settings` the CLI uses) rather than writing the file itself.

### State: wiring vs. surviving

Two kinds of module state, two rules. **Wiring** — providers/registries the composition root re-establishes on every load (cwd provider, catalog, model aliases, allowed-roots) — is plain module state. **Surviving state** — live session data that must outlive `/reload`, which re-imports the extension with fresh module instances (session state, agent mode, invoked skills, workspace runtime, daemon WebSocket) — uses `processScoped(key, init)` with keys stable across releases. Default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session. See `pi/core/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` vars on `process.env`; subagents inherit them as child processes. The non-obvious ones: `BASECAMP_REPO` is the canonical `<org>/<name>` identity (from the origin remote, falling back to the bare git basename, or the scratch-dir basename for non-repo launches) — **never** a worktree label; `BASECAMP_WORKTREE_DIR`/`LABEL` are the active worktree's path/label or empty; `BASECAMP_USER_FACING` is stamped `0` by the daemon on backgrounded workers (absent ⇒ user-facing), and the hub derives each node's `role` (`agent` vs `worker`) from it.

The worktree setup hook (the per-repo `environments.setup` command, run on creation of a new execution worktree) additionally sees `BASECAMP_REPO_ROOT` — the protected checkout path — for that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live **outside** the repo at `~/.worktrees/<org>/<name>/<label>/` to avoid polluting project directories, and **git is the source of truth** (`git worktree list --porcelain`) — Basecamp keeps no parallel metadata registry. Sessions launch with plain `pi`; Basecamp detects the repo root, treats a session launched inside a linked worktree as its active worktree, activates a worktree on implementation-plan approval, and restores the last active worktree on resume/reload/fork (or via `/worktree [label]`). Labels are a direct label or a two-level `namespace/name`: plan-approved worktrees use `wt-<user-prefix>/<slug>`; copilot-dispatched workstreams use `copilot/<slug>` (the slug is the workstream's readable id).

Legacy bare-name roots (`~/.worktrees/<repo>/`) are migrated to the `<org>/<name>` root automatically and best-effort on primary session start (`git worktree move`, skipping the main checkout, the active worktree, and anything locked or already migrated); a per-worktree failure never blocks startup.

### Workstreams

Workstreams are durable, **repo-neutral** coordination state owned by the `workstreams` domain over `#core/swarm`, persisted in the daemon's SQLite store. Identity is an internal `ws_<uuid>` plus a globally-unique three-word `slug`; content (`label`/`brief`/`constraints`) is versioned with append-only history. Worktrees are **not** persisted — git stays the source of truth, and the `copilot/<slug>` worktree name encodes the slug.

The model is multi-agent and repo-neutral: every `pi --workstream` session appends a `workstream_agents` row (additive, never overwriting), so "which repos a workstream touched" derives from its agent rows. Record shaping and execution staging are decoupled — `create_workstream`/`edit_workstream` manage the durable record, while `launch_workstream` provisions the worktree + pane and can launch into a different repo for cross-repo coordination without duplicating the record. The Logseq **dossier** (`work__<org>__<repo>__<slug>`) stays the user-facing record of priority, decisions, and blockers; one dossier may back many workstreams. On a **genuinely fresh** `--workstream` session only — never on resume/reload/fork/compact — the session attaches as an agent and the latest brief is injected.

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
