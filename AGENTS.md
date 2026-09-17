# AGENTS.md

## What is basecamp

A project-aware agent extension suite for coding agents. Configures project context, manages isolated git worktrees, and provides workflow tooling for coding sessions.

The repo is organized by the artifacts it ships:

| Product | Directory | Purpose |
|---------|-----------|---------|
| Basecamp Pi extension | `pi/` (`pi/extension.ts` + `pi/<domain>/`) | The legacy Pi package, registered from the repo root: all session, workspace, workflow, and agent behavior, assembled from domain modules |
| Basecamp OMP extension | `omp/` | The source-checkout-backed, independently loadable Oh My Pi migration target: an OMP-native file-length reminder plus package-discovered general-purpose skills, advisory TTSR rules, and workflow commands |
| `basecamp` Python distribution | `src/basecamp/` | One ordinary src-layout package: CLI/installer shell plus the `basecamp.core`, `basecamp.workspace`, `basecamp.hub` (daemon + agents dashboard), and `basecamp.omp` (migration launcher) subpackages |

`evals/` is deliberately outside the shipped products. It contains repository-local evaluation harness integrations and may depend on evaluator APIs that production Basecamp never imports.

## Repo Map

The repo root is the legacy Pi package (`package.json` / `tsconfig.json` / `biome.json`); `omp/package.json` and `omp/tsconfig.json` own the OMP extension's Bun toolchain. Python tooling is `pyproject.toml` + `install.py` + `Makefile`. Two boundary lints live in `scripts/`: `check-boundaries.ts` and `check-file-length.ts` (see File Length Limits).

`pi/` holds the legacy TypeScript extension — one domain per directory under `pi/<domain>/`, composed by `pi/extension.ts` in a fixed order (core first) — plus the Pi-owned skills under `pi/skills/`. `omp/` holds the independent OMP extension, its native file-length reminder, general-purpose skills under `omp/skills/`, advisory TTSR rules under `omp/rules/`, and workflow commands under `omp/commands/`. `src/basecamp/` holds the Python package, including the `bomp` launcher under `src/basecamp/omp/`. The per-directory layout is visible on the filesystem; domain architecture depth lives in `docs/architecture/`.

`basecamp` is one ordinary src-layout package under `src/basecamp/` — `import basecamp.<domain>` resolves to `src/basecamp/<domain>/`. (The pre-rearchitecture PEP 420 namespace-portion layout, with per-domain `py/` roots and a `check-namespace` guard, is gone.) The shared installer (`uv run install.py` initially and `basecamp install` thereafter) validates a PATH-resolved OMP with `omp --version` without changing an existing installation. Only when `omp` is missing does it require Bun and run exactly `bun install -g @oh-my-pi/pi-coding-agent`; after verifying the installed command and completing the other components, it records the source checkout that backs the extension packages.

`bomp` is an additional, PATH-based OMP migration entrypoint, not the legacy Pi default. Ordinary launches load the root `omp/` plugin from the recorded source checkout, prepend a matched project's existing additional directories, preserve every supplied OMP argument, use OMP's prompt and context discovery, never mutate OMP configuration, and directly exec OMP; `--detached` selects the disposable-worktree supervisor described below.

Legacy Pi TypeScript imports use Node subpath aliases, never parent traversal: `./sibling.ts` is the only legal relative form and every `../` is spelled `#<domain>/…`. Cross-domain, `#core/*` is free (from inside core too) and other domains resolve only via `#<domain>/index.ts`; core imports no other domain. Enforced by `scripts/check-boundaries.ts` in `npm run check`. OMP code is a separate type graph and never imports executable modules from `pi/`.

## Documentation

Documentation is layered:

- **`README.md`** — a minimal landing: what basecamp is, install, and a link to the docs site.
- **`AGENTS.md`** (this file) — cross-cutting agent-facing context: what basecamp is, the conventions that apply everywhere, and pointers to domain depth. It is injected verbatim into every system prompt, so it stays lean.
- **`docs/`** — the human-facing docs site (MkDocs Material), rendered at https://basecamp.playground.tools/. Domain architecture depth lives under `docs/architecture/`, which is what the pointers below resolve to. Agents read these files directly; the site is the rendered view.

Do **not** create design or plan documents. Planning happens through the `plan()` tool and the plan is handed to the implementer, not written to a file. Most changes need no prose at all — the code and its tests are the record. When something durable is worth writing down, it goes in the matching file above.

## Architecture Decisions

### Prompt System

The system prompt is fully **replaced**, not appended — this buys complete control but obliges basecamp to supply everything pi's default prompt would (environment context, skill/agent listings, etc.), so pi's command listings are sourced dynamically rather than assumed. Tools are the exception: their contracts reach the model through the API tools array on every request, so the prompt never lists them.

It assembles as 6 categories / 9 blocks — Constraints → Posture → Style → Capabilities → Project → Environment — each independently overridable. Two rules govern where guidance goes, and both exist because violating them produced duplication:

- **Ownership rule**: every layer answers exactly one question. `environment.md` = what is true here; `buildEnvBlock` = what is true right now; **tool description = how to call it**; `modes/*` = **what are we doing**; `styles/*` = **who you are and how you work**; `voice.md` = **how output is shaped**; `craft.md` = **how code is written**; skills = how to do it well in depth; project context = repo gotchas.
- **Consumer-divergence test**: a new block is justified only when two consumers actually disagree about it. Semantic decomposition is not a reason to split. Where the two rules conflict, divergence wins — it is about composition value, ownership only about tidiness.

The practical consequence: **tool mechanics never go in a prompt fragment.** The API tools array delivers every registered tool description verbatim (plus its parameter schema), so restating a calling contract in a fragment ships it twice in one request — a fragment should keep only what no tool description can assert (orderings, propagation rules, policy). The capabilities index accordingly lists skills and agents only. `copilot` is a mode, because it is a distinct activity; it is also the one mode that loads no role style, though voice still reaches it. What it keeps inline is copilot-specific, and a single-consumer style file would fail the divergence test. See `docs/architecture/system-prompt.md` for the block table and the full rationale.

### File-Length Guidance

The shipped Pi agent carries a cross-project **soft** source-file policy in the always-on craft block (`defaults/craft.md`), which every code-writing consumer composes — primary sessions and dispatched workers alike, so the worker contract no longer carries its own copy: TypeScript/HTML ≤350, shell ≤400, SQL ≤800, and CSS/Python/other recognized source types ≤500. Tighter project instructions win. This product guidance is separate from repository-specific hard checks such as `scripts/check-file-length.ts`.

The Pi and OMP adapters (`pi/engineering/file-length.ts` and `omp/engineering/file-length.ts`) observe only successful structured `edit`/`write` results. They read the resulting recognized source file and send one hidden, non-blocking steer while that path remains over its cap; returning under cap or settling re-arms it. The write always stands, failures stay silent, unlisted file types are exempt, and bash/code-generator mutations are intentionally outside the attribution boundary. Suppression is ephemeral runtime state.

### Browser Automation

`pi/browser/` is **primary-only** browser automation: a pinned Playwright CLI shim discovered on demand, with subagents denied. The shim blocks installs and confines automatically named artifacts to a private directory; `basecamp doctor --clean` is the sole path that reclaims the retired Puppeteer profile, and only when provably unused. See `docs/architecture/browser-policy.md` for the full runtime policy, profile lifecycle, and legacy-state contract.

### Session Modes

Agent modes are `analysis`, `planning`, `work`, and `copilot`. `work` is the default (the primary implements directly); `analysis` and `planning` are read-only / pre-implementation postures. shift+tab cycles only `analysis`/`planning`/`work` — approving an implementation plan hands off to `work`, while analysis plans stay in `analysis`. `copilot` is a locked, launch-only mode: entered solely via `pi --copilot`, immutable (shift+tab is a no-op, so it can neither enter nor leave it), and it takes precedence over `pi --workstream`. Because Pi cannot unregister or per-session-gate a tool, `plan()` is kept out of copilot by a hard `tool_call` block: it must stay registered (and therefore visible in the API tools array) because it must stay callable elsewhere, so the call-time block is the gate. Capabilities that are copilot-only (the workstream tools) or primary-only (`report_findings`) instead skip **registration** entirely, which is sound only because both predicates are resolvable at extension-load time: Pi applies flag values after extensions activate, so copilot-launch is read from `process.argv` rather than `pi.getFlag`, while subagent depth comes from the `BASECAMP_AGENT_DEPTH` env var. The `/plan` slash command is deprecated repo-wide; `plan()` and `/show-plan` remain for non-copilot sessions.

### Agent Execution Posture

Every dispatched agent runs in its **own transient git worktree**; the posture is anchored on the **deliverable**, not the tools — ad-hoc dispatches default to deliverable posture, minting a branch from clean HEAD; named report personas are report-only. Integration is always a plain `git merge agent/<handle>`; the daemon owns the full backstop chain (run-exit reap, restart reconcile, periodic sweep), and the workspace — not the toolset — is the isolation wall. See `docs/architecture/agent-dispatch.md` for the branch/teardown matrix, snapshot semantics, the capability-follows-workspace rule, and the daemon-owned backstop chain.

### Agents Dashboard

`basecamp agents` opens a read-only browser dashboard backed by a separate FastAPI app on `127.0.0.1:47658`, with process-memory-only nonce auth and a no-build packaged frontend. The hub ensure contract and one-hub invariant are shared between TypeScript and Python. See `docs/architecture/hub-daemon.md` for the dual-app topology, auth/session lifecycle, safe read model, and the no-build frontend design.

### Evaluations

Evaluation integrations live in the non-shipping top-level `evals/` package. Dependency flow is one-way: eval adapters may consume Harbor and committed Basecamp artifacts, while neither `pi/` nor `src/basecamp/` may import `evals/`.

The Terminal-Bench adapter runs one profile, **`basecamp-pi-single`** (the dispatch-enabled swarm profile was removed after evaluation showed the tasks are single-agent-shaped and their containers CPU-capped). It archives `package.json`, `package-lock.json`, and `pi/` from an exact Git commit, pins `BASECAMP_AGENT_DEPTH=1` / `MAX_DEPTH=1` to select the no-daemon, no-dispatch surface, and requires three explicit launch signals for structured mutation (`--unsafe-edit`, `--unsafe-edit-sandboxed`, `BASECAMP_EXTERNAL_SANDBOX=1`; read-only still wins). An optional `models.json` is digest-verified and installed `0600` with environment-backed credentials; no auth state or secret enters the archive. `make eval*` pins run inputs and requires a clean commit for executable runs; the profile produces local Harbor scores and Pi logs only — no ATIF and no leaderboard claim.

The archive carries no `config.json`, so the `fast` alias cannot resolve in a trial: the **bash reviewer**, which depends on it, is switched off rather than silently degraded, because its no-UI failsafe is fail-closed and would hard-block every gated command instead of judging it. `BASECAMP_BASH_REVIEWER=off` is honoured only alongside `BASECAMP_EXTERNAL_SANDBOX=1` **and** the `--unsafe-edit-sandboxed` launch flag — env and argv are independent channels, so the environment alone can never strip the gate from a real session (`loadDotenv` also refuses `BASECAMP_*` keys). Trial metadata records this state.

### Extension Modules

Legacy TypeScript ships as **one** Pi extension (`pi/extension.ts`; manifest = the repo-root `package.json`). It composes the domain modules in a **fixed order, core first**, so init is deterministic and identical on `/reload`. Each domain exposes a `register*` default export; cross-domain imports go only through `#`-subpath aliases and are boundary-checked (core imports no other domain).

The OMP migration target is a separate Bun package rooted at `omp/`; its manifest lists the ordinary `omp/extension.ts` entrypoint and the independently loadable `omp/workspace/extension.ts` policy entrypoint. The shared installer also registers only the workspace entrypoint for ambient plain-OMP discovery. OMP executable modules use only OMP APIs and never import legacy Pi code.

Core owns the substrate the other domains build on: framework UI (`pi/core/ui/`, not its own domain), git/worktree mechanics (`pi/core/git/`), the hub-daemon connector (`pi/core/hub/`), and the **agent-dispatch primitive** (`pi/core/swarm/`, `#core/swarm` — a primitive rather than a feature, because multiple domains dispatch agents). The feature domains ride on that substrate: `pull-request` owns the primary-only `/pull-request` prompt command and authoritative PR guidance skill; `code-review` owns the primary-only `/code-review` prompt command and authoritative review skill while consuming `#core/swarm`; and `workstreams` also consumes `#core/swarm`. The Python daemon and browser dashboard live under `src/basecamp/hub/`.

### OMP Scratch Workspaces

A fresh interactive `bomp` launch whose effective cwd is inside the canonical checkout is supervised in an automatic scratch. The launcher captures a coherent Git snapshot of `HEAD`, index semantics, tracked content, and nonignored untracked content without changing the source checkout; creates a detached worktree at the pinned `HEAD` through public `omp worktree add`; restores the snapshot there; and starts OMP at the corresponding nested cwd. Existing-session sources, management/headless modes, non-TTY launches, linked-worktree launches, and explicit `--direct` remain direct.

Automatic scratches carry only ephemeral launch environment describing the protected and scratch roots; OMP's transcript cwd is the sole session/worktree affinity record. On final exit, Basecamp removes the initial scratch only when it is still detached and semantically matches the launch snapshot. Branch-attached worktrees, detached commits, changed content, and uncertain Git state are retained. OMP's native `/wt <branch>` carries the current changes and session into a durable branch worktree. Private snapshot refs and temporary indexes are released after supervision; Basecamp adds no resume adapter or persistent workspace registry.

Explicit `bomp --detached` remains the clean-source, force-discard mode: it consumes its own `--detached` and source `--cwd`, starts at source `HEAD`, and always force-removes only its initial checkout after final exit. A failed removal prints the exact shell-quoted targeted Git command; never substitute `omp worktree clear --all`.

The standalone workspace extension uses live Git identity on startup, session switch, prompt, and structured mutation. Canonical interactive TUI sessions warn once per entry; every prompt distinguishes canonical, automatic-scratch, branch-worktree, and detached-worktree posture; and known filesystem targets for `write`, `edit`, `ast_edit`, and applying `lsp` operations are blocked inside every canonical checkout discovered during the session. Bash, eval, task/process, custom/MCP, raw LSP, and non-filesystem devices are intentionally outside this accidental-mutation guard.

### Diff Surface

`omp/diff` owns Basecamp's OMP-native diff/review surface: `read_diff` gives primary sessions and subagents the same merge-base-to-working-tree patch locally, while interactive-primary `annotate_diff` and `remove_annotation` keep a branch-aware journal in OMP CustomEntries. OMP `/diff` freezes that patch in a private temporary file, projects exact-range-hash-valid annotations, opens a disposable Hunk pane, binds the Hunk session to that pane's process, reads notes before close, and saves a `diff-review`; it has no `/diff last`, source snapshots, or line remapping. A completed review consumes journal entries only through its prelaunch cutoff. Legacy Pi's separate `pi/diff` surface still provides `/diff [last]`, `annotate_changeset`, per-worktree checkpoints and sidecars, and process-scoped pane recovery. See `docs/architecture/diff-surface.md`.

### Code Review

Legacy Pi keeps `/code-review [additional instructions]` as a thin primary-only prompt command over the model-invocable `code-review` skill: fixed and adaptive report-only reviewers feed a primary chair, and `report_findings` computes the deterministic verdict.

OMP instead keeps native `/review` authoritative for scope selection, diff preparation, reviewer fan-out, and structured findings. The OMP extension recognizes the native review request in model-bound context, requires the primary to validate and semantically deduplicate results, then calls `review_findings` once. That tool presents the final P0–P3 findings in a keyboard navigator, collects per-finding comments, and saves the canonical review plus feedback as a session artifact. It returns the artifact reference to the agent when session persistence is available and otherwise stores the JSON through OMP's content-addressed blob primitive and returns its readable path. See `docs/architecture/code-review.md` for both flows.

### Bash Reviewer

Every `bash` command passes one `tool_call` hook governed by a single invariant: **a static check may only restrict, never grant permission**. The domain's former 1230-line shell parser violated it — an `allow` verdict ran the command with no model consulted, making every parser gap a bypass, and the gaps that mattered were classification gaps a better parser would not have closed. The flow is now recognize-or-gate: `isTriviallySafe` (a character-class test plus a read-only executable allowlist, the only permission-granting code in the domain) or the LLM gate on the `fast` alias. **No deterministic pre-LLM block remains** — unredirected BigQuery row output, wide recursive search, mutating `git worktree` subcommands, and unrequested approving PR reviews are gate deny rules (`bq query` must write result rows to a local file; `git worktree list` is approved; approval through `gh pr review --approve`/`-a` or an equivalent API call requires explicit authorization and still routes to the user under the GitHub publication rule), so no doc or prompt fragment should describe them as mechanically blocked. The posture is fail-closed: destructive-risk approvals upgrade to `route_to_user`, subagents collapse `route_to_user` to approve only for `git-mutation`, and any reviewer failure prompts with a UI and denies without one. See `docs/architecture/bash-reviewer.md`.

### Model Aliases

Model-alias resolution is owned by `pi/core/model`, backed by the `model_aliases` section of the unified `~/.pi/basecamp/config.json`. Pi reads it **in-process**, but Basecamp (Python) is the **sole config writer** — so the `/model-aliases` TUI persists each change by shelling out to `basecamp config alias set|remove` (the same flock'd `Settings` the CLI uses) rather than writing the file itself.

### State: wiring vs. surviving

Two kinds of module state, two rules. **Wiring** — providers/registries the composition root re-establishes on every load (cwd provider, catalog, model aliases, allowed-roots) — is plain module state. **Surviving state** — live session data that must outlive `/reload` — uses `processScoped(key, init)` with keys stable across releases; renaming a key silently drops state at the next `/reload`. Default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session. This section is the canonical pattern (the public `docs/architecture/core.md` carries the layering and subsystem map only).

### Environment Variable Chain

Session launch sets `BASECAMP_*` vars on `process.env`; subagents inherit them as child processes. The non-obvious ones: `BASECAMP_REPO` is the canonical `<org>/<name>` identity (from the origin remote, falling back to the bare git basename, or the scratch-dir basename for non-repo launches) — **never** a worktree label; `BASECAMP_WORKTREE_DIR`/`LABEL` are the active worktree's path/label or empty; `BASECAMP_USER_FACING` is stamped `0` by the daemon on backgrounded workers (absent ⇒ user-facing), and the hub derives each node's `role` (`agent` vs `worker`) from it.

The worktree setup hook (the per-repo `environments.setup` command, run on creation of a new execution worktree) additionally sees `BASECAMP_REPO_ROOT` — the protected checkout path — for that exec only; it is not part of the persistent session env chain.

### Worktree Design

Worktrees live **outside** the repo at `~/.worktrees/<org>/<name>/<label>/`; git is the source of truth (`git worktree list --porcelain`) and Basecamp keeps no parallel metadata registry. The session-worktree lifecycle (issue #310 Phase 2) makes the worktree a disposable cache of its branch, with the daemon owning the agent tier and TypeScript owning the session tier under one shared lease/teardown contract; branches are never auto-deleted. Phase 3 decoupled directory names from branch identity — a generic `wt/<slug>` worktree over a uniquely-named branch — and left bare `pi` in the protected checkout, so isolation is provisioned when work earns it. See `docs/architecture/worktree-lifecycle.md` for the full lease protocol, teardown matrix, legacy-root migration, and the directory/branch decoupling.

### Workstreams

Workstreams are durable, **repo-neutral** coordination state owned by the `workstreams` domain over `#core/swarm`, persisted in the daemon's SQLite store; identity is an internal `ws_<uuid>` plus a three-word `slug`, content is versioned, and worktrees are not persisted. The model is multi-agent and cross-repo. See `docs/architecture/workstreams.md` for the tool split, content versioning, and `pi --workstream` startup behavior.

## Development

- **Python**: 3.12+, managed with `uv`
- **Install (dev)**: `uv run install.py` (installs the `basecamp` and `bomp` tools, validates or conditionally installs OMP, registers the repo root as the single Pi extension while cleaning up legacy registrations, and records the source checkout)
- **Iterate on the CLI**: `uv run install.py` installs a **non-editable** snapshot of `basecamp` on PATH, so for live iteration against your working tree run entrypoints via `uv run basecamp <cmd>` or `uv run bomp <args>` (the `uv sync` editable dev venv) rather than re-installing after each change
- **Python lint**: `uv run ruff check .` / `uv run ruff format --check .`
- **Legacy TypeScript check**: `npm run check` at the repo root (tsc whole-graph + biome + import-boundary + file-length checks)
- **OMP check**: `bun install --cwd omp --frozen-lockfile` then `bun run --cwd omp check`; OMP dependencies are isolated from the root Node graph
- **Fix**: `make fix` runs Python fixes plus `npm run lint:fix` / `npm run format`

### File Length Limits

Hard caps on every file, tests included: **TypeScript ≤ 350 lines; Python, HTML, CSS, and JavaScript ≤ 500 lines**, enforced by `scripts/check-file-length.ts` in `npm run check` (and therefore `make lint` and CI).

The cap is a module-design forcing function. When a file approaches it, split along responsibility seams — named modules with one job each. Never satisfy the cap by compressing style (collapsing blank lines, one-lining logic), and never with `-part2`-style continuation files: if no seam is apparent, the file owns more than one responsibility and the design needs rethinking, not the formatting.

There are no per-file exceptions and no suppression mechanism. (Files that predated the rule were migrated through a shrink-only `GRANDFATHERED` ratchet, burned to zero in July 2026 and removed from the script — never reintroduce per-file exceptions.)

These repository caps are hard and take precedence over the shipped Pi agent's soft reminder. The reminder provides earlier feedback after structured edits; it does not replace `npm run check` or CI.

### Testing

- **Run all**: `make test` from repo root runs the Python, legacy Node, and OMP Bun suites.
- **Python**: `uv run pytest` uses root `pyproject.toml` — `testpaths` is root `tests/`, with domain suites under `tests/core/`, `tests/workspace/`, `tests/hub/`, `tests/omp/`, `tests/config_cli/`, and `tests/evals/` beside the CLI-shell tests; imports resolve via the editable install (`uv sync`), no `pythonpath` stitching.
- **Legacy TypeScript/JavaScript**: `npm test` runs the Node test runner over every domain's `pi/<domain>/**/*.test.ts` (one child process per test file), `pi/extension.test.ts` (whole-graph load + registration under strict Node), and the pure dashboard-model tests under `tests/hub/*.test.js`. A new domain's tests must be added to the `test` glob list in `package.json`.
- **OMP TypeScript**: `bun test --cwd omp` runs `omp/**/*.test.ts` against the separately locked OMP API.
- **Tests live beside their code**: `pi/<domain>/**/tests/` and `omp/<domain>/**/tests/` (TS), and `tests/<domain>/` (Python).

## Pull Requests

`/pull-request [additional instructions]` is a thin primary-only prompt command that unconditionally directs the agent to load and apply the authoritative model-invocable `pull-request` skill. The skill owns the full guidance for handling PRs:

Open every PR **as a draft** and drive it to the user-selected stopping state in order:

1. **Open in draft.** No PR starts ready for review.
2. **Get CI green.** Poll the PR's checks (`.github/workflows/ci.yml`) and fix branch-caused failures; do not mark a red PR ready.
3. **Confirm readiness.** Green CI does not imply consent to publish for review. Ask whether to leave the PR draft or mark it ready; without explicit ready intent, stop at the green draft.
4. **Mark ready only when confirmed.** This triggers `.github/workflows/claude-review.yml`, which skips drafts.
5. **Clear the review.** Poll for the Claude review, fix every valid issue, and reply to and/or resolve every review comment before treating a ready PR as done.

The pull-request guidance never merges or closes the PR. It submits an approving review only when the user explicitly requests or authorizes that approval action; other PR instructions do not imply approval.
