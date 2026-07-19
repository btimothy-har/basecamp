# Repo Consolidation — Design

**Status:** IMPLEMENTED (phases 1–4, July 2026) · **Superseded in part** by [repo-rearchitecture](./repo-rearchitecture.md): the *Layout* (§3), *Target layout* (§4), and *Python assembly* (§6) here were replaced by the artifact-oriented layout (`pi/`, `src/basecamp/`) with the Python centralized into one ordinary package — the paired-bilingual-context layout and PEP 420 namespace-portion model below are historical. · **Scope:** Collapse 10 TypeScript Pi packages + 5 Python packages into one Pi extension and one Python distribution, laid out as paired bilingual contexts · **Decisions locked:** full merge including swarm; paired-context layout; install-time component selection dropped · **Related:** [repo-rearchitecture](./repo-rearchitecture.md), [async-agents](./async-agents.md)

This document is the design record of basecamp's package consolidation, now fully landed. File links in §1 reference pre-consolidation paths deliberately — they document the state the consolidation removed. It captures the evidence that motivated it, the decisions and rejected alternatives, the target repo shape, the assembly mechanics for each language, and a phased migration roadmap. The consolidation changes packaging and layout only — session behavior, the swarm protocol, and the `~/.pi/basecamp` config surface are unchanged.

> **Update (2026-07-11):** the Python daemon package was later renamed `basecamp.swarm` → `basecamp.hub` and re-domained (hub/swarm agents + hub/broker companion analysis); CLI is now `basecamp hub`. The TS `pi/swarm/` domain and the on-disk `~/.pi/basecamp/swarm/` path are unchanged.

---

## 1. Problem statement

basecamp is one product with one runtime: every installed TS package loads into the same Pi process, and the Python side exposes exactly one console script (`basecamp`). The packaging, however, implies a distributed system — 10 standalone npm packages (no workspace) plus a 5-member uv workspace. The boundaries do not correspond to any deployment, versioning, or publishing seam (nothing is published anywhere); their only functional role is install-time component selection, which is being dropped.

The split's topology is a star, not a mesh: `pi-core` is imported by all 9 TS siblings — 141 cross-package import edges, all deep imports into `src/` internals (only pi-core has an `exports` map, and it exports `./*`). `pi-ui` is consumed by two packages for one function; `pi-tasks` by one, type-only. Four packages (`pi-git` at 79 LOC, `pi-browser`, `pi-engineering`, `pi-bash-reviewer`) are pure leaves.

### What the split costs

- **A shared blackboard.** 20 `globalThis[Symbol.for("basecamp.*")]` registries, 13 of them in pi-core existing only so sibling extensions can share state without import cycles — ~200 lines of identical hand-rolled plumbing. Two features keep their interface+registry in pi-core and their implementation elsewhere ([tasks-access.ts](../../core/pi/src/platform/tasks-access.ts), [workspace.ts](../../core/pi/src/platform/workspace.ts) ← [service.ts](../../workspace/pi/src/workspace/service.ts)).
- **Ordering fragility as permanent API.** Cross-extension `session_start` order is undefined and changes on `/reload`, so consumers re-initialize defensively (`ensureCurrentSessionStateForEvent` in [state/index.ts](../../core/pi/src/state/index.ts), called from pi-tasks, pi-swarm, and workspace/pi).
- **Lockstep ripples.** One field on `WorkspaceState` touches 6 packages; `AgentMode` touches 5; the copilot `plan()` gate is split across pi-tasks and workspace/pi and must be edited in both.
- **Duplication to dodge dependencies.** pi-swarm re-implements pi-tasks' task-progress renderers ([local-adapters.ts](../../pi-swarm/extension/src/local-adapters.ts)) and carries a `PiSwarmDependencies` DI shim "retained for backward compat during the transition" ([dependencies.ts](../../pi-swarm/extension/src/dependencies.ts)); model-string resolution exists in two variants. On the Python side, `pi_swarm` and `companion_tui` deliberately avoid depending on `basecamp-core`, so they re-hardcode the `~/.pi/basecamp` path tree and re-implement `atomic_write_json` (5 implementations across both languages).
- **No whole-graph typechecking.** No tsconfig has `paths` or `references`; a pi-core change is not typechecked against its consumers until each of 9 packages independently runs `tsc`.
- **Toolchain ×10.** 10 × package.json / tsconfig.json / biome.json / package-lock.json / node_modules, none sharing a base. `@earendil-works/*` pins are repeated ×10 and have already drifted (`^0.78.0` vs `^0.78.1`).
- **Three hand-maintained package lists, already diverged.** [installer.py](../../src/basecamp/installer.py) (10), [Makefile](../../Makefile) (10), [ci.yml](../../.github/workflows/ci.yml) (8) — pi-bash-reviewer and pi-browser are never installed, typechecked, linted, or tested in CI. `make test` and CI also disagree on whether the root `tests/` suite runs.
- **Dev-loop tax.** Install runs 10× `npm install` + 10× `pi install`; fresh-worktree provisioning re-pays the 10 npm installs; a pi-core change requires reinstalling every `file:` dependent.

The codebase has already fought these boundaries through three successive mechanisms (hand-rolled duplicate types → injected DI interfaces → `file:` packages with deep imports) and consolidated once before (workstreams/agents moved wholesale from pi-tasks into pi-swarm). The boundaries keep losing.

## 2. Goals and non-goals

### Goals

- **One Pi extension.** A single `pi install`, a single npm toolchain (one manifest, tsconfig, biome config, lockfile, node_modules), whole-graph typechecking, deterministic in-extension init order.
- **One Python distribution.** A single `basecamp` distribution and dependency set; the uv workspace, `[tool.uv.sources]`, extras, and the pytest `pythonpath` stitch disappear.
- **Paired contexts.** Each feature's full vertical — TS module, Python partner, shared contract, skills, tests — lives in one top-level directory, generalizing the existing `pi-swarm/{extension,cli}` / `pi-companion/{pi,tui}` idiom.
- **Modularity enforced, not implied.** Module boundaries survive as folders with a uniform contract plus a cheap import-boundary lint — not as package manifests.
- **Reload safety preserved.** State that must survive `/reload` keeps the `globalThis` pattern (via one shared helper); everything else becomes plain module state.
- **The swarm protocol as a first-class contract.** `swarm/protocol/` sits beside both of its implementations.
- **Green at every phase.** Each migration phase lands with all existing tests passing and a working `pi` session.

### Non-goals

- **No behavior changes.** Session UX, tools, commands, guards, the daemon, and the wire protocol (v19) are untouched.
- **No publishing story.** Nothing moves to npm/PyPI; everything remains a local install from this repo.
- **No component selection.** The install-time picker is removed by decision, not preserved via runtime gating. Every install gets everything.
- **No swarm extraction-readiness.** Swarm is treated as core (per direction); the design does not preserve an ability to ship it separately.

## 3. Decisions and rejected alternatives

| Decision | Chosen | Rejected |
|---|---|---|
| Consolidation depth | **Full merge** — all 10 TS packages into one extension, all 5 Python packages into one distribution | *Core + swarm as second package*: keeps the machinery at exactly the boundary that uses it most (swarm is the heaviest seam consumer: 37 core import edges, the DI shim, the duplicated renderers). *Workspaces-only modernization*: fixes toolchain duplication but leaves the blackboard, ordering hazards, and deep-import fragility intact. |
| Layout | **Paired contexts** — top-level dirs holding `ts/` + `py/` (+ `protocol/`, `skills/`) per feature | *Two language trees* (`extension/` + `src/basecamp/`): fewer assembly manifests, but fragments single features across trees — the historical source of pain. |
| Component selection | **Dropped** — every install gets all modules and deps | *Runtime gating off `installed_modules`*: workable, but preserves installer complexity nobody needs. |
| Swarm identity | **One `swarm/` context** — `agents/` and `workstreams/` remain subdomains of `swarm/ts/`, exactly as laid out today | *Promoting agents/workstreams to top-level contexts*: pairing favors cohesion — the daemon and protocol serve both subdomains. |

The known trade of the full merge: one import graph means an import-time error in any module prevents the whole extension from loading, where today a broken leaf package breaks only itself. This is mitigated by whole-graph `tsc` in CI (which the split *lacks* — cross-package breaks are currently invisible until per-package builds) and by per-module `try/catch` in the composition root for runtime registration failures. The isolation being given up protects nothing in practice: everything ships together, into one process, always.

## 4. Target layout

```
basecamp/
├── package.json  tsconfig.json  biome.json  package-lock.json   # THE TS toolchain — repo root is the Pi package
├── pyproject.toml                                               # THE Python distribution
├── extension.ts                # TS composition root
├── install.py  Makefile  AGENTS.md  README.md
│
├── core/                       # ── bilingual contexts ──────────────────────────
│   ├── ts/                     #   was core/pi        (registries, session, state, model-aliases, platform)
│   └── py/basecamp/core/       #   was core/config    (paths, settings, files, exceptions)
├── workspace/
│   ├── ts/                     #   was workspace/pi   (projects, prompt assembly, worktrees, guards)
│   └── py/basecamp/workspace/  #   was workspace/projects (project/env config, interactive menus)
├── swarm/
│   ├── ts/                     #   was pi-swarm/extension src/: agents/ + workstreams/ move as-is
│   ├── py/basecamp/swarm/      #   was pi-swarm/cli   (the daemon: FastAPI/UDS, store, runner)
│   ├── protocol/               #   was pi-swarm/protocol (frames/*.json + PROTOCOL.md)
│   └── skills/                 #   was pi-swarm/extension skills
├── companion/
│   ├── ts/                     #   was pi-companion/pi  (session hooks, tmux panes, analysis registration)
│   └── py/basecamp/companion/  #   was pi-companion/tui (Textual TUI, analyzer)
│
├── ui/ts/                      # ── TS-only contexts ────────────────────────────
│                               #   was pi-ui          (footer, title, mode editor)
├── tasks/                      #   was pi-tasks       (task lifecycle, plan())
│   ├── ts/
│   └── skills/
├── git/ts/                     #   was pi-git         (/create-pr)
├── bash-reviewer/ts/           #   was pi-bash-reviewer
├── engineering/                #   was pi-engineering
│   ├── ts/
│   ├── skills/
│   └── prompts/
├── browser/ts/                 #   was pi-browser
│
├── src/basecamp/               # ── Python shell portion ────────────────────────
│   ├── cli.py  installer.py  setup.py                (unchanged location)
├── claude/                     # future: py/basecamp/claude/ launcher + plugin bundle
└── docs/  tests/  migrations/
```

### Pairing table

| Context | TS side | Python side | Shared contract |
|---|---|---|---|
| core | registries, session, state, model aliases | paths, settings, files | `~/.pi/basecamp/config.json` (py writes, ts reads), `core/model-aliases.json` |
| workspace | project context, worktrees, guards | project/env config, menus | `workspace/projects.json`, per-repo `environments` config |
| swarm | daemon client, dispatch, review, workstreams | the daemon | `swarm/protocol/` (v19 frames), `daemon.{sock,db,pid}` |
| companion | snapshot hooks, tmux panes | TUI, analyzer | snapshot/analysis files, `basecamp companion …` CLI |

Naming convention: the two language sides are always `ts/` and `py/`. A context's Python portion contributes exactly one `basecamp.<context>` subpackage; its TS side exposes exactly one `register<Context>(pi)` entry.

## 5. TypeScript assembly

### One package, sources across contexts

The repo root is the Pi package. `package.json` carries:

```jsonc
{
  "name": "basecamp",
  "type": "module",
  "pi": {
    "extensions": ["./extension.ts"],
    "skills": ["./tasks/skills", "./engineering/skills", "./swarm/skills"],
    "prompts": ["./engineering/prompts"]
  },
  "imports": {
    "#core/*": "./core/ts/*",
    "#ui/*": "./ui/ts/*",
    "#workspace/*": "./workspace/ts/*",
    "#tasks/*": "./tasks/ts/*",
    "#git/*": "./git/ts/*",
    "#bash-reviewer/*": "./bash-reviewer/ts/*",
    "#engineering/*": "./engineering/ts/*",
    "#browser/*": "./browser/ts/*",
    "#companion/*": "./companion/ts/*",
    "#swarm/*": "./swarm/ts/*"
  }
}
```

Cross-context imports use Node subpath imports (`#core/platform/workspace.ts`) — pure package.json resolution, native under `--experimental-strip-types`, supported by `tsc` (nodenext) and biome. Within-context imports stay relative. `pi install <repo>` registers once; runtime deps (`puppeteer-core`, `ws`) and the single set of `@earendil-works/*` pins live in this one manifest.

### Composition root

`extension.ts` is the only wiring manifest in the repo — it replaces the three diverged package lists and the ordering hazard:

```ts
export default function (pi: ExtensionAPI) {
  registerCore(pi);          // registries, state, session — always first, guaranteed
  registerUi(pi);
  registerWorkspace(pi);     // explicitly after core — no defensive init
  registerTasks(pi);
  registerGit(pi);
  registerBashReviewer(pi);
  registerEngineering(pi);
  registerBrowser(pi);
  registerCompanion(pi);
  registerSwarm(pi);         // composes agents + workstreams internally
}
```

Each `register*` call is wrapped so a runtime registration failure degrades that module rather than the session. Order is deterministic and identical on `/reload`.

### Boundary rules (the modularity contract)

- A context may import `#core/*` freely.
- A context may import another context **only** via its public entry (`#<context>/index.ts`).
- Relative imports may not escape the context's `ts/` directory.
- `core/ts` imports no other context.

Because every cross-context import is a `#`-specifier, the check is a small script over import specifiers, run in `make lint`. It lands in phase 1, with the move — not later.

### State rule: wiring vs. surviving state

The 20 `Symbol.for("basecamp.*")` keys split into two classes with different fates:

| Class | Examples | Fate |
|---|---|---|
| **Wiring** — existed only for cross-extension injection | exec/cwd provider, `tasksAccess`, `workspaceHooks`, catalog provider registration, copilot-launch reader, product-role, agent-identity | Plain module state. The composition root re-runs on every `/reload` and re-wires deterministically; direct imports replace the registry cells. The interface-here/impl-there splits (tasks, workspace) unify into their contexts. |
| **Surviving session data** — must outlive `/reload` | session state, agent mode, workspace runtime, live daemon WS client, panes/herdr state, skill tracker | Keep `globalThis`, via one shared `createGlobalRegistry()` helper in `core/ts` replacing ~200 lines of copy-pasted plumbing. |

The AGENTS.md "Process-Scoped Singletons" guidance shrinks accordingly: the pattern remains for reload-survival, but the cross-extension-copy problem and the handler-ordering caveat cease to exist inside basecamp.

## 6. Python assembly

`basecamp` becomes a PEP 420 namespace package assembled from portions — no top-level `__init__.py` anywhere:

- `src/basecamp/` contributes the shell modules (`cli.py`, `installer.py`, `setup.py`).
- Each bilingual context's `py/basecamp/<context>/` contributes one subpackage: `basecamp.core`, `basecamp.workspace`, `basecamp.swarm`, `basecamp.companion`.

```toml
[tool.hatch.build.targets.wheel]
packages = [
  "src/basecamp",
  "core/py/basecamp",
  "workspace/py/basecamp",
  "swarm/py/basecamp",
  "companion/py/basecamp",
]
# REQUIRED for editable installs: hatchling's default editable strategy maps by
# package name, so same-named namespace portions collapse to the last root.
# dev-mode-dirs switches editable wheels to plain sys.path entries, which is what
# PEP 420 merging needs.
dev-mode-dirs = ["src", "core/py", "workspace/py", "swarm/py", "companion/py"]
```

Consequences:

- The uv workspace, `[tool.uv.sources]`, and the 5-root pytest `pythonpath` stitch are deleted. `uv sync` installs the project editable; imports resolve normally.
- **One dependency set.** The `companion`/`swarm` extras and the `HAS_COMPANION`/`HAS_SWARM` lazy-import CLI gating are deleted; fastapi/uvicorn/textual/pydantic-ai are ordinary dependencies. The `companion`/`swarm` click groups are always present.
- `basecamp.swarm` and `basecamp.companion` import `basecamp.core.paths` and `basecamp.core.files` like any sibling — the hardcoded `~/.pi/basecamp` path derivations and the duplicate `atomic_write_json` implementations die as a side effect.
- Version lives in one place (`pyproject.toml`); `basecamp.__version__` via `importlib.metadata` if needed.

**Verification (spiked 2026-07-08, mechanism validated):** a minimal three-portion mirror of this layout was exercised end-to-end. Results:

- `uv build` — the same-basename `packages` roots merge into a single `basecamp/` tree in the wheel. ✓
- `uv sync` (editable dev install) — **fails with hatchling's default editable strategy** (its exact-location map is keyed by package name, so only the last portion root survives). With `dev-mode-dirs` (above), the editable `.pth` carries every portion root, `basecamp.__path__` shows all portions, and cross-portion imports plus pytest work with no `pythonpath` stitching. ✓
- `uv tool install -e <dir>` — console script runs against live source portions (the flow [installer.py](../../src/basecamp/installer.py) uses). ✓
- `uv tool install <dir>` (non-editable) — merged single tree in the tool venv. ✓
- Negative test: a stray `basecamp/__init__.py` in **any** portion silently shadows the namespace and makes *sibling* portions unimportable (`ModuleNotFoundError`). Phase 3 therefore adds a guard to `make lint` asserting no portion contains `basecamp/__init__.py`.

## 7. Cross-language contracts

Consolidation does not merge the languages; it puts each contract inside the context that owns it. The load-bearing surfaces, unchanged in content:

| Contract | Writer → Reader | Canonical home |
|---|---|---|
| `config.json` (install metadata, environments) | py `basecamp.core.settings` → ts `#core/platform/config.ts` | `core/` |
| `workspace/projects.json`, context/styles/prompts | py `basecamp.workspace` ↔ ts `#workspace` | `workspace/` |
| tasks store (`tasks/<session>.json`) | ts `#tasks` → py `basecamp.companion.cycles`, `basecamp.hub.store` | `tasks/` (ts writer canonical) |
| companion snapshot / analysis files | ts `#companion` ↔ py `basecamp.companion` | `companion/` |
| daemon socket/db/pid + WS frames + HTTP routes | py `basecamp.hub` (server) ↔ ts `#swarm/agents/daemon` + py `basecamp.companion.daemon` (clients) | `swarm/protocol/` |

The frame definitions remain implemented twice (TS + Python) against the JSON schemas in `swarm/protocol/`; phase 4 adds a sync test asserting both implementations match the schemas and `PROTOCOL_VERSION`, replacing today's three-way hand-sync. Path constants remain implemented once per language (`basecamp.core.paths`, `#core/platform/paths.ts`) — two implementations, each single-sourced within its language.

## 8. Install and dev-loop end state

**Installer** ([installer.py](../../src/basecamp/installer.py)) shrinks to: prerequisites → `uv tool install --force [-e] <repo>` → `npm install` at repo root → `pi install <repo>` → **stale-registration cleanup** (unregister the 10 legacy package paths recorded from the previous layout; keep the legacy list in the installer for one release). The component picker, `InstallSelection`, `_TS_PACKAGE_ORDER`, `_COMPONENT_*`, and `installed_modules` metadata are deleted (`config.json`'s `environments` section is preserved).

**Makefile** loses its package loop:

```make
test:
	uv run pytest
	npm test

lint:
	uv run ruff check . && uv run ruff format --check .
	npm run check          # tsc + biome + boundary check

fix:
	uv run ruff check --fix . && uv run ruff format .
	npm run lint:fix && npm run format
```

**CI** becomes: checkout → uv → ruff ×2 → node → `npm ci` → typecheck → lint (incl. boundary check) → pytest → `npm test`. One of everything, nothing omitted, and caching becomes trivial (one lockfile).

| Task | Today | Target |
|---|---|---|
| Bump `@earendil-works/*` SDK | edit 10 package.jsons (drift already present) | 1 file |
| Change a shared type | touch up to 6 packages; no cross-check until each builds | 1 edit; `tsc` validates all consumers |
| Fresh worktree provisioning | 10× npm install | `uv sync && npm ci` |
| Install | component picker + 10× npm install + 10× `pi install` | 3 commands |
| CI | 8× (ci+typecheck+lint+test), missing 2 packages | 1× each, missing nothing |
| `/reload` init order | undefined across extensions, changes per reload | deterministic (one composition root) |

## 9. Migration risks

- **Shared fate at import time.** One bad import breaks the whole extension load. Mitigation: whole-graph `tsc` + boundary lint in CI from phase 1; per-module try/catch in the composition root.
- **Hatchling editable + namespace portions.** ~~Unproven~~ **Validated by spike (§6)** — requires `dev-mode-dirs`; residual risk is a stray `basecamp/__init__.py` shadowing sibling portions, guarded by a lint check. The single-`src/`-tree fallback remains documented in case a future hatchling change regresses `dev-mode-dirs` behavior.
- **Stale Pi registrations.** Existing installs carry 10 registered package paths that will dangle after the move. Mitigation: installer cleanup step (§8) plus a README note for manual `pi uninstall`.
- **History and blame.** Moves use `git mv` (content unchanged in the move commits); import-rewrite commits are recorded in `.git-blame-ignore-revs`.
- **Behavior drift during seam collapse (phase 2).** The riskiest phase by nature. Mitigation: behavior-preserving diffs only, one seam per commit, the full 79-TS-file + 31-Python-file test suite as the gate, and `/code-review` on the branch.
- **Docs debt.** AGENTS.md (repo map, singleton guidance, testing section), core/pi README's canonical-pattern reference, and the design docs' file links all reference old paths. Rewritten in phase 4 (final), with AGENTS.md's repo map becoming a 1:1 mirror of the context dirs.

## 10. Phased roadmap

Each phase is a PR that lands green (all tests passing, working `pi` session, `basecamp install` functional).

1. ✅ **TS consolidation (mechanical).** Create root `package.json`/`tsconfig`/`biome`; `git mv` each package's `src/` into `<context>/ts/` (skills/prompts to `<context>/skills|prompts/`); rewrite cross-package specifiers to `#`-subpath imports; write `extension.ts` composing the ten `register*` entries in today's install order; land the boundary-check script; update Makefile/CI/installer (single npm install + single `pi install` + stale cleanup; picker removed). globalThis keys untouched. Gate: all TS tests green under the single runner; session smoke (`pi` in a repo, worktree flow, `/reload`).
2. ✅ **Seam collapse (behavior-preserving).** Delete `PiSwarmDependencies`/`local-adapters` duplicates and the duplicated task renderers; unify model resolution; fold the tasks-access and workspace interface/impl splits into their contexts; convert wiring-class registries to direct imports; introduce `createGlobalRegistry()` for the surviving-state keys; remove `ensureCurrentSessionStateForEvent` defensive call sites (init order is now guaranteed); unify the two-layer copilot `plan()` gate. Gate: tests green; grep shows no orphaned seam machinery.
3. ✅ **Python consolidation.** (Namespace-portion editable install already spike-validated — §6.) Move `core/config` → `core/py`, `workspace/projects` → `workspace/py`, `pi-swarm/cli` → `swarm/py`, `pi-companion/tui` → `companion/py` with `dev-mode-dirs` configured; add the no-`basecamp/__init__.py` lint guard; delete the uv workspace/sources/extras and pytest `pythonpath`; point `basecamp.swarm`/`basecamp.companion` at `basecamp.core` paths/files helpers; delete `HAS_*` gating. Gate: `uv run pytest` green; `uv tool install -e .` then daemon + TUI + installer smoke.
4. ✅ **Contracts and docs.** Protocol sync test (TS + Python frames vs `swarm/protocol/` schemas and version); rewrite AGENTS.md (repo map, singletons, development/testing sections), core README pattern references, and design-doc links. The TS↔Python frame sync test predated phase 4 (daemon-frames.test.ts asserts PROTOCOL_VERSION equality against frames.py and both sides validate the fixture set), so no new machinery was needed.

## 11. Open items

- **Protocol codegen** (generate both frame implementations from the JSON schemas) — deliberately deferred; the phase-4 sync test captures most of the value at a fraction of the machinery.
- **`src/basecamp/` shell portion** — could later fold into `core/py` if a root `src/` tree feels vestigial once `claude/` lands; not worth deciding now.
- **Skill/prompt hoisting** — skills stay within their contexts; revisit only if the Claude Code launcher's bundling (which projects skills from a manifest) prefers a single root.
- **`uv.lock`** — currently untracked while 10 npm lockfiles are tracked; consolidation is the natural moment to start tracking it (one lockfile per language).
