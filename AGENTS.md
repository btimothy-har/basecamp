# AGENTS.md

## What is basecamp

A project-aware Pi extension suite for AI coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

The repo is organized by the artifacts it ships:

| Product | Directory | Purpose |
|---------|-----------|---------|
| Basecamp Pi extension | `pi/` (`pi/extension.ts` + `pi/<domain>/`) | The single Pi package, registered from the repo root: all session, workspace, workflow, and agent behavior, assembled from domain modules |
| `basecamp` Python distribution | `src/basecamp/` | One ordinary src-layout package: CLI/installer shell plus the `basecamp.core`, `basecamp.workspace`, and `basecamp.hub` (daemon + agents dashboard) subpackages |

`evals/` is deliberately outside both shipped products. It contains repository-local evaluation harness integrations and may depend on evaluator APIs that production Basecamp never imports.

## Repo Map

The repo root is the Pi package (`package.json` / `tsconfig.json` / `biome.json`); Python tooling is `pyproject.toml` + `install.py` + `Makefile`. Two boundary lints live in `scripts/`: `check-boundaries.ts` and `check-file-length.ts` (see File Length Limits).

`pi/` holds the TypeScript extension — one domain per directory under `pi/<domain>/`, composed by `pi/extension.ts` in a fixed order (core first). `src/basecamp/` holds the Python package. The per-directory layout is visible on the filesystem; each domain has a `README.md` for depth.

`basecamp` is one ordinary src-layout package under `src/basecamp/` — `import basecamp.<domain>` resolves to `src/basecamp/<domain>/`. (The pre-rearchitecture PEP 420 namespace-portion layout, with per-domain `py/` roots and a `check-namespace` guard, is gone.)

TypeScript imports use Node subpath aliases, never parent traversal: `./sibling.ts` is the only legal relative form and every `../` is spelled `#<domain>/…`. Cross-domain, `#core/*` is free (from inside core too) and other domains resolve only via `#<domain>/index.ts`; core imports no other domain. Enforced by `scripts/check-boundaries.ts` in `npm run check`.

## Documentation

Documentation is layered:

- **`README.md`** — anything user-facing.
- **`AGENTS.md`** (this file) — cross-cutting agent-facing context: what basecamp is, the conventions that apply everywhere, and pointers to domain depth. It is injected verbatim into every system prompt, so it stays lean.
- **Per-domain `README.md`** — depth for a single domain: architecture decisions, invariants, and rationale a reader can't reconstruct from the source alone.

Do **not** create design or plan documents. Planning happens through the `plan()` tool and the plan is handed to the implementer, not written to a file. Most changes need no prose at all — the code and its tests are the record. When something durable is worth writing down, it goes in the matching file above.

## Architecture Decisions

### Prompt System

The system prompt is fully **replaced**, not appended — this buys complete control but obliges basecamp to supply everything pi's default prompt would (environment context, tool/skill listings, etc.), so pi's tool and command listings are sourced dynamically rather than assumed.

It assembles as 6 categories / 8 blocks — Constraints → Posture → Style → Capabilities → Project → Environment — each independently overridable. Two rules govern where guidance goes, and both exist because violating them produced duplication:

- **Ownership rule**: every layer answers exactly one question. `environment.md` = what is true here; `buildEnvBlock` = what is true right now; **tool description = how to call it**; `modes/*` = **what are we doing**; `styles/*` = **how it is achieved**; skills = how to do it well in depth; project context = repo gotchas.
- **Consumer-divergence test**: a new block is justified only when two consumers actually disagree about it. Semantic decomposition is not a reason to split. Where the two rules conflict, divergence wins — it is about composition value, ownership only about tidiness.

The practical consequence: **tool mechanics never go in a prompt fragment.** The capabilities index injects every registered tool description verbatim, so restating a calling contract in a fragment ships it twice in one prompt — a fragment should keep only what no tool description can assert (orderings, propagation rules, policy). `copilot` is a mode, because it is a distinct activity; it is also the one mode that loads no style, carrying its own short manner section because no existing style fits and a single-consumer style file would fail the divergence test. See `pi/system-prompt/README.md` for the block table and the full rationale.

### File-Length Guidance

The shipped Pi agent carries a cross-project **soft** source-file policy in the always-on craft block (`defaults/styles/craft.md`), which every code-writing consumer composes — primary sessions and the mutative worker alike, so the worker no longer carries its own copy: TypeScript/HTML ≤350, shell ≤400, SQL ≤800, and CSS/Python/other recognized source types ≤500. Tighter project instructions win. This product guidance is separate from repository-specific hard checks such as `scripts/check-file-length.ts`.

`pi/engineering/file-length.ts` observes only successful structured `edit`/`write` results. It reads the resulting recognized source file and sends one hidden, non-blocking steer while that path remains over its cap; returning under cap or settling re-arms it. The write always stands, failures stay silent, unlisted file types are exempt, and bash/code-generator mutations are intentionally outside the attribution boundary. Suppression is ephemeral wiring state, not `processScoped` surviving state.

### Browser Automation

`pi/browser/` is **primary-only** browser automation: a pinned Playwright CLI shim discovered on demand, with subagents denied. The shim blocks installs and confines automatically named artifacts to a private directory; `basecamp doctor --clean` is the sole path that reclaims the retired Puppeteer profile, and only when provably unused. See `pi/browser/README.md` for the full runtime policy, profile lifecycle, and legacy-state contract.

### Session Modes

Agent modes are `analysis`, `planning`, `work`, and `copilot`. `work` is the default (the primary implements directly); `analysis` and `planning` are read-only / pre-implementation postures. shift+tab cycles only `analysis`/`planning`/`work` — approving an implementation plan hands off to `work`, while analysis plans stay in `analysis`. `copilot` is a locked, launch-only mode: entered solely via `pi --copilot`, immutable (shift+tab is a no-op, so it can neither enter nor leave it), and it takes precedence over `pi --workstream`. Because Pi cannot unregister or per-session-gate a tool, `plan()` is kept out of copilot by two independent layers sharing one predicate — a hard `tool_call` block plus a capabilities-index filter — rather than a single gate. `plan()` needs both because it must stay callable elsewhere; capabilities that are copilot-only (the workstream tools) or primary-only (`report_findings`) instead skip **registration** entirely, which is sound only because both predicates are resolvable at extension-load time: Pi applies flag values after extensions activate, so copilot-launch is read from `process.argv` rather than `pi.getFlag`, while subagent depth comes from the `BASECAMP_AGENT_DEPTH` env var. The `/plan` slash command is deprecated repo-wide; `plan()` and `/show-plan` remain for non-copilot sessions.

### Agent Execution Posture

Every dispatched agent runs in its **own transient git worktree**; the posture is anchored on the **deliverable**, not the tools — only `worker` (persona `deliverable: true`) mints a branch, every other run is report-only. Integration is always a plain `git merge agent/<handle>`; the daemon owns the full backstop chain (run-exit reap, restart reconcile, periodic sweep), and the workspace — not the toolset — is the isolation wall. See `pi/core/swarm/README.md` for the branch/teardown matrix, snapshot semantics, the capability-follows-workspace rule, and the daemon-owned backstop chain.

### Agents Dashboard

`basecamp agents` opens a read-only browser dashboard backed by a separate FastAPI app on `127.0.0.1:47658`, with process-memory-only nonce auth and a no-build packaged frontend. The hub ensure contract and one-hub invariant are shared between TypeScript and Python. See `src/basecamp/hub/README.md` for the dual-app topology, auth/session lifecycle, safe read model, and frontend constraints.

### Evaluations

Evaluation integrations live in the non-shipping top-level `evals/` package. Dependency flow is one-way: eval adapters may consume Harbor and committed Basecamp artifacts, while neither `pi/` nor `src/basecamp/` may import `evals/`.

The Terminal-Bench adapter exposes the `basecamp-pi-single` profile: it archives `package.json`, `package-lock.json`, and `pi/` from an exact Git commit, pins `BASECAMP_AGENT_DEPTH=1` / `MAX_DEPTH=1` to select the no-daemon, no-dispatch surface, and requires three explicit launch signals for structured mutation (`--unsafe-edit`, `--unsafe-edit-sandboxed`, `BASECAMP_EXTERNAL_SANDBOX=1`; read-only still wins, flags are not inherited by daemon-spawned children). An optional `models.json` is digest-verified and installed `0600` with environment-backed credentials; no auth state or secret enters the archive. `make eval*` pins run inputs and requires a clean commit for executable runs; this profile produces local Harbor scores and Pi logs only — no ATIF, leaderboard claim, or complete accounting of auxiliary bash-reviewer model calls.

### Extension Modules

All TypeScript ships as **one** Pi extension (`pi/extension.ts`; manifest = the repo-root `package.json`). It composes the domain modules in a **fixed order, core first**, so init is deterministic and identical on `/reload`. Each domain exposes a `register*` default export; cross-domain imports go only through `#`-subpath aliases and are boundary-checked (core imports no other domain).

Core owns the substrate the other domains build on: framework UI (`pi/core/ui/`, not its own domain), git/worktree mechanics (`pi/core/git/`), the hub-daemon connector (`pi/core/hub/`), and the **agent-dispatch primitive** (`pi/core/swarm/`, `#core/swarm` — a primitive rather than a feature, because multiple domains dispatch agents). The feature domains ride on that substrate: `pull-request` owns the primary-only PR lifecycle skill, while `code-review` and `workstreams` consume `#core/swarm`. The Python daemon and browser dashboard live under `src/basecamp/hub/`.

### Diff Surface

`/diff` is Basecamp's diff/review surface: primary-only, hard-dependent on both Herdr and an installed `hunk`, scoped to `merge-base(defaultBranch, HEAD)` as a single `git diff` target so committed and uncommitted work show together. It blocks the session while you review, then returns your inline notes as line-anchored feedback; `annotate_changeset` lets the working agent seed its own rationale onto the same diff. The constraints that shape it — why the block is load-bearing, why sidecars are launch-only, and why every `herdr pane run` argument is quoted — are in `pi/diff/README.md`.

### Code Review

`/skill:code-review` is a primary-only, user-invoked independent review of the current branch: it dispatches fixed and adaptive report-only reviewers, the primary synthesizes and semantically deduplicates their reports, and `report_findings` computes a deterministic verdict over that final set. Manual only. See `pi/code-review/README.md` for the review method, flow, result handling, and verdict rules.

### Continuation Guard

The `tasks` domain judges every stop and nudges the agent onward when it stopped prematurely, hooking **`agent_end`** — the moment an agent stops working. `turn_end` is wrong (it fires per LLM response *inside* a run) and `agent_settled` is wrong (it fires after Pi's continuation loop has exited, which in a dispatched agent's print-mode process is already too late); a `followUp` queued at `agent_end` is what makes Pi continue. It lives in `tasks`, not `core`, because core imports no other domain and the judgment needs goal/task state. Mechanical preconditions (`provider_error`, active plan handoff, queued user input, nudge cap, abort) decide only whether the hook may act; a single `fast`-model call against the Q/D/H/I/R/E rubric is the sole authority on whether the stop was premature. Task state is **evidence inside category R, not a gate** — gating on open tasks would be escapable by marking them complete, and for the same reason **no tool argument ends the loop**: `complete_task` has no `stop_work`, because a self-declared stop was both escapable by a peer `followUp` and the main way a run ended with no assistant text to report. Closing out is a work summary, recognised by veto D. Abort state and queued input are re-read *after* the judge returns, since Pi resumes on any queued message without checking for an abort. The nudge is **static** (two texts, one per context) so model-authored text never reaches an agent through a system-trusted frame. The posture is **fail-open**, the inverse of the bash reviewer: no alias, no verdict, or any error means no nudge, because a wrong stop costs a keystroke while a wrong continue burns a run — and the `fast` alias is a shared dependency, not an off switch. See `pi/tasks/README.md`.

### Model Aliases

Model-alias resolution is owned by `pi/core/model`, backed by the `model_aliases` section of the unified `~/.pi/basecamp/config.json`. Pi reads it **in-process**, but Basecamp (Python) is the **sole config writer** — so the `/model-aliases` TUI persists each change by shelling out to `basecamp config alias set|remove` (the same flock'd `Settings` the CLI uses) rather than writing the file itself.

### State: wiring vs. surviving

Two kinds of module state, two rules. **Wiring** — providers/registries the composition root re-establishes on every load (cwd provider, catalog, model aliases, allowed-roots) — is plain module state. **Surviving state** — live session data that must outlive `/reload` — uses `processScoped(key, init)` with keys stable across releases. Default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session. See `pi/core/README.md` for the canonical pattern.

### Environment Variable Chain

Session launch sets `BASECAMP_*` vars on `process.env`; subagents inherit them as child processes. The non-obvious ones: `BASECAMP_REPO` is the canonical `<org>/<name>` identity (from the origin remote, falling back to the bare git basename, or the scratch-dir basename for non-repo launches) — **never** a worktree label; `BASECAMP_WORKTREE_DIR`/`LABEL` are the active worktree's path/label or empty; `BASECAMP_USER_FACING` is stamped `0` by the daemon on backgrounded workers (absent ⇒ user-facing), and the hub derives each node's `role` (`agent` vs `worker`) from it.

The worktree setup hook (the per-repo `environments.setup` command, run on creation of a new execution worktree) additionally sees `BASECAMP_REPO_ROOT` — the protected checkout path — for that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live **outside** the repo at `~/.worktrees/<org>/<name>/<label>/`; git is the source of truth (`git worktree list --porcelain`) and Basecamp keeps no parallel metadata registry. The session-worktree lifecycle (issue #310 Phase 2) makes the worktree a disposable cache of its branch, with the daemon owning the agent tier and TypeScript owning the session tier under one shared lease/teardown contract; branches are never auto-deleted. Phase 3 decoupled directory names from branch identity — a generic `wt/<slug>` worktree over a uniquely-named branch — and left bare `pi` in the protected checkout, so isolation is provisioned when work earns it. See `pi/core/git/README.md` for the full lease protocol, teardown matrix, legacy-root migration, and the Phase 3 decoupling.

### Workstreams

Workstreams are durable, **repo-neutral** coordination state owned by the `workstreams` domain over `#core/swarm`, persisted in the daemon's SQLite store; identity is an internal `ws_<uuid>` plus a three-word `slug`, content is versioned, and worktrees are not persisted. The model is multi-agent and cross-repo. See `pi/workstreams/README.md` for the tool split, content versioning, and `pi --workstream` startup behavior.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py` (installs the `basecamp` tool, then registers the repo root as the single Pi extension, cleaning up legacy per-package registrations)
- **Iterate on the CLI**: `uv run install.py` installs a **non-editable** snapshot of `basecamp` on PATH, so for live iteration against your working tree run the CLI via `uv run basecamp <cmd>` (the `uv sync` editable dev venv) rather than re-installing after each change
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **TypeScript check**: `npm run check` at the repo root (tsc whole-graph + biome + import-boundary + file-length checks); `make lint` runs it after the Python checks
- **Fix**: `make fix` runs Python fixes plus `npm run lint:fix` / `npm run format`

### File Length Limits

Hard caps on every file, tests included: **TypeScript ≤ 350 lines; Python, HTML, CSS, and JavaScript ≤ 500 lines**, enforced by `scripts/check-file-length.ts` in `npm run check` (and therefore `make lint` and CI).

The cap is a module-design forcing function. When a file approaches it, split along responsibility seams — named modules with one job each. Never satisfy the cap by compressing style (collapsing blank lines, one-lining logic), and never with `-part2`-style continuation files: if no seam is apparent, the file owns more than one responsibility and the design needs rethinking, not the formatting.

There are no per-file exceptions and no suppression mechanism. (Files that predated the rule were migrated through a shrink-only `GRANDFATHERED` ratchet, burned to zero in July 2026 and removed from the script — never reintroduce per-file exceptions.)

These repository caps are hard and take precedence over the shipped Pi agent's soft reminder. The reminder provides earlier feedback after structured edits; it does not replace `npm run check` or CI.

### Testing

- **Run all**: `make test` from repo root runs `uv run pytest` plus `npm test`.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths` is root `tests/`, with domain suites under `tests/core/`, `tests/workspace/`, `tests/hub/`, `tests/config_cli/`, and `tests/evals/` beside the CLI-shell tests; imports resolve via the editable install (`uv sync`), no `pythonpath` stitching.
- **TypeScript/JavaScript**: `npm test` runs the Node test runner over every domain's `pi/<domain>/**/*.test.ts` (one child process per test file), `pi/extension.test.ts` (whole-graph load + registration under strict Node), and the pure dashboard-model tests under `tests/hub/*.test.js`. A new domain's tests must be added to the `test` glob list in `package.json`.
- **Tests live beside their code**: `pi/<domain>/**/tests/` (TS) and `tests/<domain>/` (Python).

## Pull Requests

Open every PR **as a draft** and drive it to the user-selected stopping state in order:

1. **Open in draft.** No PR starts ready for review.
2. **Get CI green.** Poll the PR's checks (`.github/workflows/ci.yml`) and fix branch-caused failures; do not mark a red PR ready.
3. **Confirm readiness.** Green CI does not imply consent to publish for review. Ask whether to leave the PR draft or mark it ready; without explicit ready intent, stop at the green draft.
4. **Mark ready only when confirmed.** This triggers `.github/workflows/claude-review.yml`, which skips drafts.
5. **Clear the review.** Poll for the Claude review, fix every valid issue, and reply to and/or resolve every review comment before treating a ready PR as done.

The pull-request workflow never merges, closes, or approves the PR.
