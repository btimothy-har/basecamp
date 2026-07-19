# Repo Re-Architecture — Artifact-Oriented Layout

**Status:** DESIGN LOCKED (top level + innards principle, 2026-07-09) · execution not started · **Scope:** reorganize the repo top level by *shipped artifact*, centralize the Python into one ordinary package, and regroup each domain's innards under a two-layer rule · **Supersedes:** the *Layout* decision (§3), the Target layout (§4), and the Python assembly (§6) of [repo-consolidation](./repo-consolidation.md) · **Related:** [repo-consolidation](./repo-consolidation.md)

> **Update (2026-07-11):** the Python `swarm` package documented below was later renamed to `basecamp.hub` and re-domained — `hub/swarm/` (agent coordination) + `hub/broker/` (companion analysis), with the store decomposed per data object and the CLI now `basecamp hub`. This record describes the rearchitecture's original output; the TS `pi/swarm/` domain and the on-disk `~/.pi/basecamp/swarm/` runtime path are unchanged.

This is the design record for basecamp's second structural pass. The [consolidation](./repo-consolidation.md) collapsed 15 packages into one Pi extension and one Python distribution — it fixed *packaging*. This pass fixes *navigability*: what the top level says the project is, and how each domain's files are grouped. It is layout-only — session behavior, the swarm protocol (v19), and the `~/.pi/basecamp` config surface are unchanged, and no product source-import statement changes (§7).

---

## 1. Problem statement

The consolidation left the repo laid out as **paired bilingual contexts** — a top-level directory per feature, each holding `ts/` + `py/` (+ `protocol/`, `skills/`). That was the right intermediate, but two problems remain, both navigability:

- **The top level is untiered.** ~19 peer directories mix the architecture (the 10 contexts) with scaffolding (`src/`, `tests/`, `migrations/`, `scripts/`, `docs/`, a placeholder `claude/`) and root config, with no signal which is which. Weight is flattened: `git/` (4 files) sits beside `swarm/` (215). AGENTS.md's repo map has already drifted — it omits `migrations/` and understates `tests/`.
- **The innards are inconsistent.** Flat piles (`companion/ts` = 11 loose files, `ui/ts` = 8) sit next to properly-subdivided contexts (`core/`, `swarm/`). Directories masquerade as filename prefixes (`title-*`, `herdr-*`, `daemon_*`). The Python nests deep and repetitive (`core/py/basecamp/core/settings.py`). Non-index files carry an `-index` suffix beside the real `index.ts`.

## 2. What the repo actually ships

The organizing insight: the repo ships **three artifacts, intertwined over one shared body of domains.** None owns a separate pile of code — each is an *assembly* over the domains.

| Artifact | What it is | Assembled from |
|---|---|---|
| Pi extension | the TypeScript extension loaded into a Pi session | `pi/extension.ts` + each domain's TS |
| `basecamp` Python package | the `basecamp` CLI, daemon, and TUI | `src/basecamp/` (CLI shell) + each domain's Python |
| Claude extension *(future)* | a Claude Code launcher | `claude/` + reused prompt/skill/Python assets |

The **domains** — `core workspace swarm companion ui tasks git bash-reviewer engineering browser` — are the shared vocabulary. A domain is *bilingual* when it has both a TS and a Python side; 4 of 10 are (core, workspace, swarm, companion). The domain name is the same on both sides (`pi/core` ⟷ `src/basecamp/core`, `#core/*` ⟷ `import basecamp.core`), so the two artifacts speak one language. *(The daemon domain later became the lone exception: after the hub rename its Python side is `basecamp.hub` while its TS side keeps `pi/swarm/` — see the update note above.)*

## 3. Decisions and rejected alternatives

| Decision | Chosen | Rejected |
|---|---|---|
| Top-level axis | **By artifact** — `pi/`, `src/basecamp/`, `claude/` | *By bilingual context* (status quo): untiered, exposes the 10 innards at the top. *One `src/` hiding everything*: minimal root, but buries the artifact narrative one level down — a single-artifact layout applied to a three-artifact repo. |
| Python location | **Centralized** into one `src/basecamp/` package | *Colocated per domain* (`<domain>/py/basecamp/<domain>/`): deep and repetitive, scatters the distribution across 4+ dirs, and needs the whole PEP 420 namespace-portion apparatus to reassemble. |
| TS wrapper | **Drop `ts/`** — TS sits at each domain root under `pi/` | *Keep `ts/`*: redundant once `py/` leaves the domain; TS is the extension's native language and needs no quarantine. |
| Container naming | **Name by function** (`pi/`), mirror the domain vocabulary | *`contexts/`*: "context" already means prompt/project context in this codebase. *`modules/`*: generic; says nothing about what it is. |
| Innards grouping | **Two layers** — external-system adapters by system, features by functionality (§5.3) | *By responsibility only*: scatters a single external-system integration (e.g. herdr) across the features that consume it. |

### On reversing the "two language trees" rejection

Consolidation §3 rejected two language trees as "the historical source of pain." Centralizing the Python is a step back toward that shape, so the reversal is deliberate and bounded:

- The pain the consolidation actually removed was **15 packages × toolchains** — one manifest each, three diverged CI/install lists, 141 deep-import edges, DI shims. Centralizing the Python keeps every bit of that fixed: still one `package.json`, one `pyproject.toml`, one import graph. This pass only changes the *physical directory* of already-unified code.
- The per-domain ts↔py coupling is **contract-mediated and cross-process** — the swarm wire protocol, the companion snapshot files, the daemon socket. These are separate programs that talk over a boundary, not an interwoven call graph, so "a feature spanning two trees" costs little in practice for exactly these domains.
- In exchange we get a top level that reads as what it ships, a conventional Python package, and the **deletion of the namespace-portion machinery** (§5.2).

## 4. Target top-level

```
basecamp/
│  package.json  tsconfig.json  biome.json            # TS toolchain (repo root = the Pi package)
│  pyproject.toml  uv.lock  install.py  Makefile       # Python toolchain + bootstrap
│  README.md  AGENTS.md  CLAUDE.md  LICENSE
│
├─ pi/                     # ① the Pi extension (TypeScript)
│    extension.ts          #    composition root
│    core/ workspace/ swarm/ companion/                #    bilingual domains — TS side
│    ui/ tasks/ git/ bash-reviewer/ engineering/ browser/   #    TS-only domains
│
├─ src/basecamp/           # ② the basecamp Python package (one ordinary package)
│    core/ workspace/ swarm/ companion/                #    bilingual domains — Python side
│    cli.py  installer.py  setup.py                    #    the basecamp CLI shell
│
├─ claude/                 # ③ the Claude extension (reserved; launcher later)
│
└─ docs/  scripts/
```

Four meaningful directories (`pi`, `src`, `claude`, `docs`/`scripts`) plus root config, down from ~19. The `#<domain>/*` import-boundary contract (core importable freely; other domains only via their `index.ts`; core imports no other domain) carries over unchanged — it is simply re-anchored from `<domain>/ts/` to `pi/<domain>/`.

## 5. Principles

### 5.1 Name by function; mirror the domain vocabulary

Roots are named for what they *are* (`pi/`, `claude/` are the extensions; `src/basecamp/` is the package they wrap), not generically. The domain decomposition is identical on both language sides; the two sides need not mirror *internally* (see §6 — companion's TS has `panes/`, its Python has a TUI and a daemon client), because they are genuinely different programs.

### 5.2 Centralize the Python (delete the portion machinery)

`src/basecamp/` becomes one ordinary package. Each `<domain>/py/basecamp/<domain>/` moves to `src/basecamp/<domain>/`; `import basecamp.<domain>` is unchanged. This deletes, wholesale:

- `pyproject.toml`: `packages` collapses from 5 portion roots to `["src/basecamp"]`; `dev-mode-dirs` is removed.
- `install.py`: the 5-entry `sys.path` portion list collapses to one.
- `Makefile`: the `check-namespace` guard (no `basecamp/__init__.py`) becomes moot.
- The "PEP 420 namespace package assembled from portions" model — gone. It existed *only* to support scattering.

### 5.3 Two-layer innards: adapters vs. features

Within a domain, group in two layers:

1. **External-system adapters** — code whose job is to speak to a specific external system. Grouped *by the system* and called out explicitly (`herdr/`, `tmux/`, `chrome/`, `bigquery/`, `llm/`, `daemon/`, `git/`, `store/`). The driver layer.
2. **Features** — general functionality, grouped by what it does (`panes/`, `snapshot/`, `analysis`, `triage/`). Features define a port; adapters implement it.

The payoff: an external integration stays cohesive. When herdr's CLI changes you touch `herdr/`, not the two features that consume it. Do **not** split an integration across features by "responsibility."

The mapping pass (§6) sharpened the rule into these working definitions:

- **What is an adapter.** An *external program or service* you shell out to, socket to, spawn, or call over a network or an LLM API — git CLI, tmux, herdr, Chrome/CDP, the swarm daemon, SQLite, FastAPI/uvicorn, the model provider. An adapter owns **both** halves of its integration: request-building *and* response-parsing (e.g. `bq` invocation + its JSON-output parser; the daemon transport + its frame codec).
- **What is *not* an adapter.** In-process UI/render toolkits (Textual, rich, questionary, `pi-tui`, a pygments wrapper) — those are the ambient toolkit, so their code is *feature*-level. The host API (Pi `ExtensionAPI`) is a host seam, not an integration. And filesystem reads/writes of *basecamp's own state* (snapshots, session-state, `config.json`, `model-aliases.json`, the tasks store) are features — "external system" means a *foreign* system, not any syscall.
- **Ports are a fourth category.** Companion's model — a feature owns its port, an adapter in the same domain implements it — does not cover core's cross-domain seams (`WorkspaceService`, `CatalogProvider`, `SessionProductRoleProvider`, the model-alias registry). Those are *defined* in core but *implemented in other domains*, so they have no owning feature in core and touch no external system. They live in core's `platform/` seam layer (§6.2).
- **Placement.** Adapters sit at the **domain root**, as peers of the features — so "what external systems does this domain touch?" is answerable by listing the domain's dirs. This holds even for a single-consumer adapter (`ui/llm/` serves only `title/`). **A dir only when ≥2 files** — a one-file adapter or feature stays a file (`llm.py`, `swarm/workstreams/herdr.ts`, `footer.ts`).
- **LLM calls → `<domain>/llm/`**, uniformly (ui, bash-reviewer, companion-py). Each domain owns its own model usage; there is no central LLM module.

### 5.4 Tagging the session surface

"Feature" is broad, so each feature is tagged by what it registers into a Pi session — its *surface* — which keeps a module's contribution legible:

- `[tool]` — agent-callable (`escalate`, `skill`, `bq_query`)
- `[command]` — slash command or keybinding (`/model-aliases`, shift+tab)
- `[mode]` — agent mode
- `[widget]` — anything that renders (footer, dialog, overlay, pane)
- `[hook]` / `[guard]` — event handlers and gates (`session_start`, `tool_call`)
- `[provider]` — fills a core port (catalog, cwd, workspace-service, alias)

Non-surface tags: `[state]`, internal `[logic]`, `[adapter]`, `[port]`. Tag everywhere; **promote a kind to its own dir only when it clusters** — a lone tool stays with its feature (`skill` lives in `capabilities/`), but a real cluster earns a `tools/` dir (swarm, browser, tasks).

## 6. Innards, domain by domain

All ten domains mapped against §5.3 (one parallel reader each). Trees show the target under `pi/<domain>/` (TS) / `src/basecamp/<domain>/` (Python); `# adapter` bands are external-system drivers, everything else is a feature. **Open decisions are marked ⟐** and consolidated in §6.12.

Three findings recurred everywhere and are worth stating once:

- **Core owns the shared low-level adapters** (git/worktree, `exec`/spawn, `env`, the model provider). So most domains have *no* adapter of their own — they consume core's via a port (git, tasks, workspace TS all delegate their "git" work to `#core`). The exceptions that carry their own adapters are the ones that are genuinely separate processes: swarm (the daemon) and companion-py (a standalone TUI/analyzer that shells its own git and calls its own LLM).
- **The same three cleanups repeat**: kill the `<domain>/ts/<domain>/` name-echo dir; promote misleading `-index`/wrapper files into honest `<subsystem>/index.ts`; drop filename prefixes that duplicate a folder (`title-*`, `herdr-*`, `daemon_*`, `browser-*`).
- **Adapters are rare; features dominate.** Three domains (tasks, git, workspace-TS) have *no* external-system adapter at all — the rule there collapses to "features by functionality."

### 6.1 core — TS + Python  ✅ LOCKED

Core is the one domain whose deep subpaths are public API (`#core/*`, ~145 external import sites), so **internal** core moves rewrite specifiers repo-wide (§7).

```
pi/core/
  index.ts                                         # registerCore

  # ── session-scoped features ──
  agent-mode/     [mode] the 5 modes + shift+tab cycle · [command] mode shortcut · copilot-launch flag
  session/        pi session/thread metadata + lifecycle: session-id · registration · compaction
                  buildUserContext — transcript→prompt compactor (← ui; shared with companion)
    state/        [state] session-state record: cell · persistence · fork              (was #core/state/, ×11)
  project/        [hook] session_start: resolve project → BASECAMP_PROJECT · [provider] allowed-roots   ← workspace
                  resolve · state · context (doc loader/discovery, shared with workspace/prompt) · injection [hook] nested-doc

  # ── other features ──
  capabilities/   [tool] skill() · [hook] skill lifecycle · [provider] catalog   (+ skill-tracker.ts ← platform/)
  escalate/       [tool] escalate · [widget] escalate dialog
  model-aliases/  [command] /model-aliases + overlays · [provider] native-config alias
  worktree/       [logic] worktree policy — naming · affinity · migration          ← core/ts/workspace/

  # ── adapters ──
  git/            [adapter] git CLI driver (repo · worktree)                        ← teased from core/ts/workspace/
  platform/       [adapter] runtime seams: env · exec · paths · config · model-resolution · global-registry
                  [port]    workspace (×39) · catalog · product-role · model-aliases

src/basecamp/core/   settings · paths · files · exceptions · projects · migrations · directories  (+ tests/)   [projects ← workspace]
```

- **`project/` + `context-injection` moved in from workspace** (both core-clean — session setup, not composition): `project/` = resolution + state + the shared context-file loader + the nested-doc injection `[hook]`; `core/py` gains `projects.py` · `migrations.py` · `directories.py` (+ the project-management CLI). `workspace/prompt` stays put and imports the loader from `#core`.
- **`agent-mode/` standalone** — absorbs the mode cell + `cycleAgentMode`, the shift+tab command, `copilot-launch`, and the `AgentMode` enum (which `session/state/` imports). `session/` is pure session/thread metadata + lifecycle, calling into `agent-mode/` to set the initial mode (one-directional).
- **`state/` nests under `session/`** — it's the session's persisted record. Accepted cost: `#core/state/*` → `#core/session/state/*` (×11).
- **`core/ts/workspace/` splits** into `git/` (the one real TS git adapter) + `worktree/` (policy), killing the triple-`workspace` clash.
- **`platform/skill-tracker.ts` → `capabilities/`** (misplaced state + name clash).
- **Ports stay in `platform/`** (the seam layer), not a dedicated `ports/` — hoisting rewrites the hottest import (×39) for taxonomy only.

### 6.2 swarm — TS + Python  ✅ LOCKED

Already the best-structured domain; the work is deltas.

```
pi/swarm/
  index.ts   README.md
  protocol/          shared wire contract: PROTOCOL.md · frames/*.json     ← swarm/protocol/ (§7)
  skills/agents/
  # ── adapter ──
  daemon/            [adapter] the daemon transport (UDS · WS · HTTP)      ← HOISTED from agents/daemon/
    connection · rpc · http · spawn · process · paths · client · frames/ (codec) · view/ · index (lifecycle)
  # ── features ──
  agents/
    index.ts · types · errors · extension-root
    catalog/ [provider] · launch/ [logic] (+ handles · retry)
    tools/ [tool] dispatch · ask · cancel · list · wait · peer-messages (+ delivery)
    reporting/ [logic] · ui/ [widget] active-agents + statusline · review/ [command] /code-review
  workstreams/       [tool] launch_workstream · list_workstreams · set_workstream_status  (+ herdr.ts [adapter])

src/basecamp/swarm/
  __init__.py  frames.py  run_result.py     wire contract + models
  transport/  app · server                  [adapter] FastAPI/uvicorn over UDS
  store/                                     [adapter] SQLite persistence
  runner/     runner · process              [adapter] subprocess — dispatched Pi processes
  service/                                   [feature] transport-independent orchestration (dispatch · cancel · messaging · reaper · waiting · …)
  registry.py                                [feature] in-memory runtime state
```

- **Daemon hoisted** to `pi/swarm/daemon/` (both `agents/` and `workstreams/` consume it); consumers lifted into `agents/{tools,reporting,ui}`. `registerDaemonClient`'s lifecycle keeps one adapter→feature edge (or defer that extraction).
- Python adapters grouped (`transport/`, `runner/`) to match `store/`; `service/`+`registry` are the features.
- Hazard (§7): TS `daemon-frames.test.ts` reads the Python `frames.py` source across `pi/`↔`src/` — hardcoded path, linter-blind, hand-fix + green `make test`.

### 6.3 workspace — TS + Python  ✅ LOCKED  *(superseded 2026-07-10: `prompt/` carved to `system-prompt`, then the whole domain folded into `core/workspace/` — see §9)*

Reduced to its true scope — **worktrees + edit guards** — after `projects`/`context-injection` moved to core and the banner to ui. No git adapter here; worktree ops delegate to `#core`'s git port.

```
pi/workspace/
  index.ts  README.md
  worktree/       [command] /worktree · [hook] session_start bootstrap/restore/migrate · [provider] WorkspaceService + cwd
                  (index ← service · session · command) — consumes #core git + core/worktree policy
  guards/         [guard] tool_call/user_bash: protect the checkout · retarget edits into the worktree  (index ← guards · unsafe-edit)
  prompt/         [hook] before_agent_start: assemble the replacement system prompt   (carved out 2026-07-10 → the `system-prompt` domain; see §9)
                  (fragment-builders + system-prompts/ assets; context-file loader pulled from #core)

src/basecamp/workspace/
  environments.py · cli/(environment) · env display     # per-repo worktree-setup config + its menu
```

- **Outflows:** `projects` + `context-injection` → **core** (§6.1); `header.ts` (session-start banner) → **ui** (§6.5).
- `context.ts` split on the load/build seam — its **context-file loader** went to core (feeds `context-injection` there, and `prompt/` imports it back via `#core`); its **fragment-builders** stayed with `prompt/`.
- `environments.py` is the per-repo **worktree-setup** config (the `setup` command), *not* the prompt's `environment.md` asset — so it stays here with `worktree/`. Read in core (`worktree/setup.ts`), managed by this Python CLI.

### 6.4 companion — TS + Python  ✅ LOCKED

TS — all `[hook]`s + the two pane adapters:

```
pi/companion/
  index.ts        registers the three hooks
  analysis.ts     [hook] turn_end → run session analysis (spawns the py analyzer; #core buildUserContext)
  snapshot/       [hook] session events → write snapshot + report to herdr   (index = writer · model)
  panes/          [hook] session_start/shutdown → create/reuse/close the pane   (index · provider = port · state · command)
  herdr/          [adapter] herdr pane — provider · metadata
  tmux/           [adapter] tmux pane — provider · commands
```

Python — standalone TUI + analyzer (`companion dashboard`/`analyze`); adapter/feature tags only:

```
src/basecamp/companion/
  __init__.py  app.py            # [entry] Textual TUI composition root → `companion dashboard`
  llm.py                         # [adapter] LLM (pydantic-ai)
  daemon/  client · models · parse    # [adapter] swarm daemon over UDS/HTTP  ← daemon.py + daemon_models + daemon_parse
  git/     runner · commands           # [adapter] git CLI  ← carved out of diff.py
  analysis/  model · generate          #  feature  ← analysis.py + analyzer.py   → `companion analyze`
  diff/      model · collect           #  feature  pure diff math ← the non-git half of diff.py
  snapshot.py  cycles.py               #  snapshot + goal-cycle data
  source.py  poll.py                   #  dashboard-data  (poll.py ← sources.py, de-homonymized)
  ui/                                  #  the TUI widgets (Textual/pygments = toolkit, not adapters)
```

- `diff.py` (479 LOC, near cap) splits on the seam: git driver → `git/`, pure diff math → `diff/` (forced by the cap anyway).
- `git/` is companion's *own* git adapter — separate process, can't use `#core`'s (the "separate processes carry their own adapters" exception).
- API byte-identical via `__init__.py` re-exports; the one edit is `analyzer.py`'s sibling path (`cli.py` + its test, or a shim).
- **Follow-up (deferred, behavior-adjacent):** companion's `daemon/` models+parse *overlap* swarm's daemon protocol — three "daemon" implementations (swarm/py server, swarm/ts client, companion/py client) reimplement the wire shape. Consolidating to a shared daemon-client/models is a later split, not this pass.

### 6.5 ui — TS  ✅ LOCKED  *(superseded 2026-07-10: folded into `core/ui` as a core submodule — see §9 post-execution refinement)*

```
pi/ui/
  index.ts
  footer.ts       [widget] the 3-line footer
  header.ts       [widget] session-start status banner              ← workspace
  title.ts        [widget] title · /title · turn_end hook          (was title/index.ts; context.ts → core)
  editor.ts       [widget] mode-aware editor border                (was mode-editor.ts)
  mode.ts         [logic]  mode color/label vocab — footer + editor read it   (was mode-style.ts)
  llm/            [adapter] title generation: generate · model
```

- `buildTitleContext` was a shared conversation compactor (title-gen *and* companion analysis), not a title concern — it moves to `core/session/` as `buildUserContext`, killing the companion→ui edge.
- Everything is a flat single-file feature; only the 2-file `llm/` adapter keeps a folder. **A folder that drops to one file collapses** — this also corrects the mapper's `bash-reviewer/llm/` and `browser/chrome/` (each one file → `bash-reviewer/llm.ts`, `browser/chrome.ts`).

### 6.6 tasks — TS · no adapters  ✅ LOCKED  *(superseded 2026-07-10: re-layered into schemas/·lifecycle/·workflows/·tools/ — see §9)*

```
pi/tasks/
  index.ts        registerTasks
  render.ts       [logic] shared ✓/… tool-result widgets (both features use it)
  lifecycle/      ← tasks/ts/tasks/ name-echo renamed
    index.ts (was tasks.ts) · tools.ts [tool] the 7 task tools · gate.ts [guard] · widget.ts [widget]
    context.ts [logic] · store.ts [state] · access.ts [state] TasksAccess + types
  planning/       the plan() flow
    index.ts [tool] plan() · commands.ts [command] /show-plan
    draft/ (draft · draft-logic) · handoff/ (handoff · worktree-choices · worktree-setup)
    review/ [widget] (review · review-model · review-render · task-cards) · guards/ [guard] (plan-copilot · plan-skill)
  skills/  gather · planning
```

- `planning/` sub-grouped (not 13 flat files) — each sub-dir is a real ≥2-file cluster, killing the `review-*`/`worktree-*`/`plan-*-guard` prefix families.
- `plan-copilot-guard` — *superseded 2026-07-10:* the shared predicate moved to `core/agent-mode` as `isCopilotMode` (+ `PLAN_TOOL_NAME`), killing the `workspace/prompt → #tasks` edge (see §9 post-execution refinement). The guard itself stays here.
- `lifecycle/tools.ts` (322 lines, near the cap) kept as one `[tool]` file; split to `tools/` only if it grows.

### 6.7 engineering — TS  ✅ LOCKED  *(superseded 2026-07-10: `bq-query/` + `bigquery/` merged into one `bigquery/` module — see §9)*

The whole code side is one tool (`bq_query`):

```
pi/engineering/
  index.ts        registerEngineering
  bq-query/       [tool] bq_query — dry-run → scan-approval → execute → job-metadata
    index.ts (was tools/bq-query.ts) · params · approval · format · render · sql-files   [logic]
  bigquery/       [adapter] the bq CLI — cli.ts (spawns bq) · job-summary.ts (parses its JSON)
  skills/         data-analysis · data-warehousing · marimo · pi-development · python-development · sql
  prompts/        tophat.md
```
Doesn't flatten (6-file feature; `engineering` is broader than the one tool). The generic `tools/` bucket dissolves. Adapter named `bigquery/` (the system, not the `bq` binary).

### 6.8 git — TS · no adapter  ✅ LOCKED

```
pi/git/
  index.ts     registerGit
  pr.ts        [command] /create-pr — prompt builder + default-base resolution (via #core exec)
```
Flat, no adapter dir — the one git touch (symbolic-ref) delegates to `#core`'s exec; `commands.ts` → `pr.ts`.

### 6.9 bash-reviewer — TS  ✅ LOCKED

```
pi/bash-reviewer/
  index.ts        [guard] tool_call on bash — assembles ReviewDeps, runs the review  (merges outer + reviewer/ wrappers)
  review.ts       [logic] gating policy — triage → LLM gate → fail-closed/route/confirm; owns the ReviewDeps port
  triage/         [logic] deterministic classifier pipeline (index ← triage · rules · shell-lex · classify-git · classify-commands)
  llm.ts          [adapter] the LLM safety gate — implements ReviewDeps  (was llm/gate.ts, collapsed per one-file rule)
```

### 6.10 browser — TS  ✅ LOCKED

```
pi/browser/
  index.ts        registerBrowser — the 2 tools + [hook] session_shutdown disconnect
  tools/          [tool] eval.ts (browser_eval) · screenshot.ts (browser_screenshot)   (browser- prefix dropped)
  chrome.ts       [adapter] Chrome/Brave over CDP (puppeteer): launch · connect · page lifecycle  (was chrome/connection.ts — one file)
```
Follow-up (not layout): dedupe `scratchDir()`/`timestampForFile()` across the two tools into `tools/output.ts`.

> **Post-rearchitecture update (2026-07-15):** the custom Puppeteer/CDP adapter and both Pi tools were retired. The current `pi/browser/` domain contains an exact-pinned `@playwright/cli` shim (`bin/playwright-cli`), a Basecamp-owned on-demand skill (`skills/playwright-cli/`), primary/subagent resource and PATH policy in `index.ts`, and focused tests. Playwright now owns a fresh persistent profile; legacy profile/process state is untouched.

### 6.11 companion-py test & Python-portion note

Python tests move beside their code to `src/basecamp/<domain>/tests/` (in-package). This ships them in the wheel unless excluded — a packaging call for the executor; the alternative is a repo-root `tests/<domain>/`. Either way `pyproject.toml` `testpaths` re-point per §5.2.

### 6.12 Open decisions (consolidated)

| # | Domain | Decision | Lean |
|---|---|---|---|
| ⟐1 | core | Ports in `platform/` (umbrella seam layer) vs. a dedicated `ports/` dir | `platform/` (avoids rewriting the ×39 hottest import) |
| ⟐2 | core | Internal churn budget — accept only the 2 high-value moves, leave the rest | Yes, minimal |
| ⟐3 | swarm | Hoist the daemon adapter + split its consumer features vs. keep the daemon-client subsystem cohesive | Hoist (correct two-layer answer; fallback documented) |
| ⟐4 | tasks | `planning/` flat (13 files) vs. light sub-group (`review/`, `handoff/`) | Light sub-group |
| ⟐5 | naming | `bigquery/` vs `bq/`; `chrome/` vs `cdp/`; core `git/` vs `vcs/`; `tasks/lifecycle/` rename | system-name; `chrome/`; `git/`; `lifecycle/` |
| ⟐6 | follow-ups | Behavior-adjacent splits beyond layout-only: `diff.py` (forced by cap anyway), core `worktree.ts` git-verb teasing, workspace `cli/environment.py` repo-identity dedup | Defer to follow-ups |

## 7. Migration mechanics — why it's cheap

Both languages already decouple the physical directory from the import path, so the move is manifests + `git mv`, not a source rewrite:

- **TS:** cross-domain imports are `#<domain>/*` subpaths. For the **9 sealed domains**, only the *targets* in `package.json` `imports` change (`./swarm/ts/*` → `./pi/swarm/*`); every `import … from "#swarm/…"` is byte-identical, and relative imports move as whole subtrees.
- **Python:** `basecamp.<domain>` is unchanged; only the portion roots the manifests enumerate move. Regrouping a Python domain *internally* stays byte-identical by naming each new subpackage after the old module and re-exporting its names from `__init__.py` (§6.4).

**The core exception.** `#core/*` is the one *unsealed* boundary — deep subpaths are public API (~145 sites). The top-level `core/ts → pi/core` re-anchor is byte-identical, but any **internal** core regrouping (e.g. `core/ts/workspace/` → `git/`+`worktree/`) rewrites `#core/...` specifiers across every consuming domain. That is why §6.1 regroups core minimally — each internal move is repo-wide.

Manifests to update: `package.json` (`imports`, `pi.extensions`/`skills`/`prompts`, test globs), `pyproject.toml` (collapse per §5.2), `install.py`, `Makefile`, `scripts/check-boundaries.ts` (re-anchor to `pi/<domain>`), `biome.json` (the `swarm/protocol` exclude). Moves use `git mv`; import-target commits go in `.git-blame-ignore-revs`.

**Known cost — shared cross-language artifacts lose their above-both-languages home.** `swarm/protocol/` currently sits above `ts/`+`py/`; centralizing splits swarm across `pi/swarm/` and `src/basecamp/swarm/`, so the contract picks a side (`pi/swarm/protocol/`), Python tests reading its JSON fixtures by path. Each domain's `README` likewise lands on the `pi/` side.

**Linter-blind hazards (hand-fix + green `make test`).** The boundary checker sees only *import specifiers*; hardcoded **filesystem paths** are invisible to it, and several cross the trees the split creates:
- **swarm (sharpest).** `swarm/ts/agents/tests/daemon-frames.test.ts` reads the *Python* `frames.py` source to assert `PROTOCOL_VERSION` parity — after the split that read crosses `pi/swarm/…` → `src/basecamp/swarm/frames.py`. Its Python sibling `test_daemon_frames.py` resolves the fixture dir by relative depth. Both re-point, and the fixtures move to `pi/swarm/protocol/frames/`.
- **workspace.** `…/cli/project.py` builds a `system-prompts/styles` path that *already* doesn't match today's layout — re-true it to `pi/workspace/prompt/system-prompts/` *(later moved again to `pi/system-prompt/defaults/styles` — §9)*, or prompt-loading silently returns empty.
- **companion-py.** Folding `analyzer.py` breaks the sibling module path `basecamp.companion.analyzer` — fix `cli.py` + its test, or leave a shim (§6.4).

## 8. Doc truing (at execution)

Docs are rewritten in lockstep with the move, never ahead of it — AGENTS.md is loaded as live session instructions (`CLAUDE.md` is `@AGENTS.md`), so a premature rewrite mis-instructs every session:

- **AGENTS.md** — Repo Map rewrite, artifact table, ~12 inline path refs, and **deletion** of the namespace-package section and its `make lint` guard note.
- **README.md** — the same two-artifact description.
- **This repo's per-domain `README.md`s** — each describes its `ts/`+`py/` split.
- **`scripts/check-boundaries.ts` / `check-file-length.ts`** doc-comments — they cite AGENTS.md sections and the "context" model.
- **[repo-consolidation.md](./repo-consolidation.md)** — gets a "superseded in part" pointer to this doc.

## 9. Sequencing & status

- **Top level:** LOCKED · **DONE.**
- **Innards principle (§5.3–5.4):** LOCKED.
- **Per-domain innards:** designed and LOCKED for all 10 (§6).

### Execution — done (relocation-first, green at every step)

Shipped as a sequence of `make lint` + `make test`-green commits:

1. **Relocation** — every TS domain re-anchored to `pi/<domain>/`, Python centralized to `src/basecamp/` (portion machinery deleted), manifests + the three linter-blind path hazards (§7) fixed.
2. **Leaf domains** — git, browser, engineering, bash-reviewer (§6.7–6.10).
3. **tasks** — `lifecycle/` + `planning/` sub-clusters (§6.6).
4. **companion** — TS `panes/`·`herdr/`·`tmux/`·`snapshot/`; Python `daemon/` & `analysis/` groupings, `sources.py → poll.py` (§6.4).
5. **core** — `agent-mode/` standalone + `state/` nested under `session/` (§6.1).
6. **ui** — flatten + `buildUserContext → core/session` (§6.5).
7. **project → core** + `workspace/prompt/` + `header → ui` (§6.1, §6.3, §6.5) — the central boundary move.
8. **workspace** — `worktree/` + `guards/` (§6.3).
9. **Doc truing** (§8) — AGENTS.md, README.md, this doc.

### Deferred (consciously, doc-sanctioned) — follow-ups, not shipped this pass

- **swarm internals (§6.2)** — the daemon hoist + consumer split (TS) and the `transport/`·`runner/` grouping (Python), per §6.12 ⟐3's cohesive-subsystem fallback and §6.2's defer note. The TS `agents/daemon/` is a 37-file dense subtree; the Python side would break ~30 monkeypatch string-paths *and* the runtime `-m basecamp.swarm.runner` invocation. Swarm keeps its already-best-structured layout, relocated to `pi/swarm/` + `src/basecamp/swarm/`.
- **core minimal-churn (§6.12 ⟐2)** — the `git/`+`worktree/` split of `core/ts/workspace/` and `platform/skill-tracker.ts → capabilities/` were left in place; the `SESSION_STATE_AGENT_MODES` enum stays in `session/state` (agent-mode imports it) rather than reversing ownership.
- **companion `diff.py → git/ + diff/` carve (§6.12 ⟐6)** — behavior-adjacent; `diff.py` is under the 500-cap.
- The earlier behavior-adjacent list: carve `prompt/` to its own domain; consolidate the three `daemon` impls onto a shared wire contract; tease git verbs out of core `worktree.ts`; dedupe workspace `cli/environment.py` repo-identity against core; `browser/tools/output.ts` dedupe; split `tasks/lifecycle/tools.ts` only if it grows.

### Post-execution refinement (2026-07-10, same branch) — dependency-graph tidy

After the layout landed, a cross-domain import-graph audit motivated two small green follow-ups. The audit found the coupling is a near-perfect star — every domain imports `core`, max out-degree 2, and only three non-core edges existed (`companion→tasks`, `workspace→tasks`, `swarm→ui`). These follow-ups are symbol/submodule relocations, **not** domain moves:

1. **`ui` → `core/ui` (core submodule).** `ui` was framework chrome (footer/header/title/mode/llm) sitting as a peer domain, yet `core` already owned sibling framework UI (`escalate`'s dialogs). Folded `pi/ui/` into `pi/core/ui/` with `registerCore` registering it last, alongside `escalate`/`capabilities`. Principle: *framework UI lives with the framework; feature-specific widgets (task cards, agent rows, panes) stay with their feature.* Dropped the `#ui/*` alias and the `ui` entries in `CONTEXTS`/`extension.ts`; the one external consumer (`swarm`'s daemon widget → `formatTitle`) now imports `#core/ui/index.ts`. `ui` in-degree → 0; boundary check reports **9 contexts**.
2. **plan-gate predicate → `core/agent-mode`, renamed `isCopilotMode`.** `isPlanDisabledFor(mode)` was a one-line predicate over `AgentMode` in `tasks/planning/guards/plan-copilot.ts`; `plan()` is a Pi built-in that basecamp only *gates*, so `PLAN_TOOL_NAME` was never tasks-owned. Moved both to `core/agent-mode` (the predicate renamed `isCopilotMode` — the pure mode fact). Killed the `workspace→tasks` edge; the tasks guard and workspace's capabilities filter both consult `core`.

Net graph after both: a single hub (`core`) whose only remaining inter-feature edge is `companion→tasks` (live task-state observation through the public index — the boundary system working as intended, kept). This supersedes the `isPlanDisabledFor` note in §6.6 and the peer-domain framing of §6.5.

### Core internals restructured (2026-07-10, same branch) — concept-homes, no `platform` bucket

A pass to make every core sub-directory name a *concept* rather than a role. The trigger was `platform/`: a bucket named for its mechanism ("where things go to dodge the dependency rule") that mixed genuine primitives with cross-domain ports. The pattern (ports in core) is load-bearing and stays; the *bucket* was the smell, so it was dissolved and every file re-homed to the concept it serves. Shipped as seven `make lint` + `make test`-green commits:

1. **escalate** — the 3 interactive-dialog files clustered under `escalate/dialog/` (index/flow/view); tool/render/types stay at the root.
2. **agent-mode** — `command.ts` (a keyboard shortcut, not a command) → `toggle.ts`; the copilot specifics (launch reader, `isCopilotMode`, `PLAN_TOOL_NAME`) gathered into `copilot.ts`, leaving `index.ts` the generic state machine.
3. **agent-role** — `platform/product-role.ts` → `core/agent-role.ts` (renamed, sibling to agent-mode). Stays in core: swarm registers it and both the swarm daemon and `tasks/planning` read it, so it can't move to swarm without a `tasks→swarm` edge.
4. **skills + catalog** — `capabilities/` (a vague umbrella) split into `skills/` (the `skill()` tool + `tracker.ts`, store+lifecycle merged) and `catalog/` (the tool/skill registry port + providers).
5. **model** — `model-aliases/` → `model/`, absorbing the two platform model seams: the alias registry merges into `model/index.ts`, `model-resolution.ts` → `model/resolution.ts`, `config.ts` → `aliases.ts`.
6. **workspace service** — `platform/workspace.ts` (the fan-in-26 port) → `core/workspace/service.ts`, beside core's own workspace defaults.
7. **host + root primitive** — `env`·`exec`·`paths`·`config` → `host/` (the runtime boundary); `global-registry.ts` (the reload-survival primitive, not a host concern) sits at the core root. `platform/` deleted.

Every directory now names a concept; `#core/*` deep paths retarget accordingly (the `platform` dissolution alone rewrote ~106 specifiers across 75 files — the largest sweep, uniform because the transform was just "drop `platform/`"). The ports did not leave core — they moved next to the concept they serve.

### engineering flattened to one `bigquery/` module (2026-07-10, same branch) — a boundary the code didn't honor

§6.7 split engineering's one tool into `bq-query/` (feature) and `bigquery/` (bq-CLI adapter). The adapter/feature convention earns its keep when *several* features share an adapter (`herdr/`, `tmux/`) — engineering has exactly one feature, so nothing was being kept from scattering. Worse, the "layer" wasn't one: the two directories imported *each other*. `bigquery/cli.ts` and `job-summary.ts` reached back *up* into `bq-query/params.ts` for their own I/O types (`BqCaptureResult`, `BqFileResult`, `BQ_TIMEOUT_MS`, `MAX_ERROR_CHARS`, the summary shapes), while `bq-query/` pulled the run/summarize fns down — a bidirectional edge, so the directory boundary announced a layering the code never respected, under two near-homonym names. Merged all eight files into one `bigquery/` module (named for the system — leaves room for a future `postgres/` sibling); the cross-directory imports collapse to same-directory `./`. Purely internal to `pi/engineering/` — no manifest, test, or boundary-config change. This supersedes §6.7's "doesn't flatten" and its separate-`bigquery/`-adapter framing.

### tasks re-layered by function (2026-07-10, same branch) — layers, not sibling features

§6.6 split tasks into `lifecycle/` + `planning/` as if they were two features, but `planning/` only ever depended *downward* on `lifecycle/` (one-way `activateGoalCycle`) — they were layers wearing a sibling costume. tasks is *one* feature (managed work: propose it, track it), so within it the honest cut is by function, per the rule **feature is top-level organization; within a feature, organize by function.** Re-cut into four layers, one green commit each:

1. **`schemas/`** — the shared data models (task family + plan family), the import-nothing leaf. Membership rule: a type lands here only when more than one layer (or an outside domain) needs it; single-layer working types (handoff mechanics, review-view helpers) stay next to their use.
2. **`lifecycle/`** — the durable state machine only (runtime, `goal-cycle.ts` ops, `store.ts`, `widget.ts`, session handlers). The 5-method `TasksAccess` port — which served exactly one external call (companion's `getState`), with two dead methods (`setNotes`, `getContext`) — collapses to a read-only `TasksReader` (`reader.ts`); read-only is now a compile guarantee, not a hope. Intra-domain mutations become direct `goal-cycle.ts` calls, deduping the archive+start logic `update_goal` and `plan()` each copied.
3. **`workflows/`** — the stateless plan procedures: `draft.ts` (merged from draft-logic + draft/index), `review/`, `handoff/`.
4. **`tools/`** — the thin agent-facing surface (task-tools, plan-tool, commands, guards, render). Renders dissolve into the layer they render — no `ui/` bucket. `plan()` sheds its ~85-line worktree choreography into `workflows/handoff`'s `runHandoff()` (a discriminated outcome the tool maps to its result), dropping 327→252 lines and every `#core/workspace` import; the `agent-role` seam moves with the reuse logic into handoff.

The composition root wires the task tools + guards, so the `tools → lifecycle` dependency points downward (lifecycle registers neither). Both former near-cap files (plan 327, task-tools 322) come down. Purely internal to `pi/tasks/` plus a 3-line `companion` ripple (`getTasksAccess` → `getTasksReader`); no manifest or boundary-config change. This supersedes §6.6's `lifecycle/`+`planning/` layout and the `TasksAccess` framing.

### system-prompt carved out of workspace (2026-07-10, same branch) — the deferred prompt-domain split

§6.3 parked `prompt/` inside `workspace/` with a "carve out to its own domain later" note, because it was a composition root that imported `#tasks` (to gate `plan()`) and so couldn't be core. The post-execution refinement had already killed that edge by hoisting `isCopilotMode` + `PLAN_TOOL_NAME` into `core/agent-mode`, leaving `prompt/` importing only `#core/*` — so the carve is now free.

`pi/workspace/prompt/` → new top-level **`pi/system-prompt/`** domain: `prompt.ts`, `context-builders.ts`, `defaults/` (was `system-prompts/`), and the two prompt tests. Registered in `extension.ts` right after `workspace`; it binds at `before_agent_start`, so registration order isn't load-bearing. A near-pure move — the only content edit inside a moved file is `prompt.ts`'s `PACKAGE_DIR` (`system-prompts` → `defaults`).

**project stays wholly in core** — deliberately *not* split into a state-cell-vs-resolver, because `core/ui/header.ts` reads project state and core may not import a domain. It is still registered from `workspace/index.ts` for `session_start` ordering; that module's docstring, which had falsely claimed core registers it, is corrected. Wiring: `package.json` `#system-prompt/*` + test glob, boundary `CONTEXTS` → **10**, and the Python style-scanner path (`cli/project.py`) + its test re-trued to `pi/system-prompt/defaults/styles`. Supersedes §6.3's `prompt/`-in-workspace layout.

### workspace folded into core/workspace (2026-07-10, same branch) — the domain was an adapter for a core-owned port

After `prompt/` left, `pi/workspace/` was just the runtime that *implemented* a port core already owned (`core/workspace/service.ts`) plus the git primitives — it imported only `#core/*`, was the sole implementation with one registrant, and was even consumed by core's own ui. So it wasn't really a domain. Folded whole into `core/workspace/`: `worktree/service.ts → runtime.ts`, `session.ts`, `command.ts`, `guards.ts`, `unsafe-edit.ts`, tests; the `#core/*` imports in the moved files became relative. `registerCore` now registers `registerWorkspace(pi)` then `registerProject(pi)` in sequence — dissolving the ordering hack where the workspace domain reached into core to register project. Domain gone: the `#workspace/*` alias, the `extension.ts` MODULES entry, the workspace test glob; boundary check → **9 contexts**.

Then the `WorkspaceService` port seam was **collapsed** (per the user: no internal seams) — the interface + `registerWorkspaceService`/`getWorkspaceService`/`requireWorkspaceService` registry are deleted; `service.ts`'s accessors read the runtime directly; `getWorkspaceEffectiveCwd()` is null-safe and `onWorkspaceChange()` added; the 7 `getWorkspaceService()` consumers move to those accessors. The allowed-roots registry stays (a real multi-registrant seam); `runtime.ts` imports its types from `service.ts` type-only to keep the value edge one-way. Finally the two now-dead `registerCore` shims (default cwd provider, stub git-detection) were removed. Three green commits (fold · collapse · shim-drop). Supersedes §6.3 entirely — workspace is a core subsystem, not a domain. `project` stays in core, unchanged.

### git + project consolidated (2026-07-10, same branch) — one git home, one project home

Two cuts on the freshly-folded `core/workspace/`. **(1) git.** The git plumbing (`worktree.ts`, `repo.ts`, `worktree-target.ts`, `migrate.ts`) was consumed by swarm + tasks and had nothing to do with the workspace *runtime*, so it moved to a dedicated **`core/git/`** (`worktrees/{crud,target,migrate}.ts` + `repo.ts`); the 49-line `pi/git/` domain (`/create-pr`) folded in as `core/git/{pr,index}.ts`, dissolving another domain → **8 contexts**. **(2) project.** `core/workspace/` (runtime) and `core/project/` (config/context) were one concept split — the config even lives in `…/workspace/projects.json`, project's `session_start` reads workspace state, and both set `BASECAMP_*`. Merged into **`core/project/`**: the runtime becomes `project/workspace/` (`service.ts → state.ts`), `context-injection.ts → injection.ts`, `repo-logseq.ts → logseq.ts`, and `project.ts` + `session.ts` fold into `config.ts` (resolver + state cell + session in one). `registerProject` now sequences workspace-bootstrap → project-resolve → context-injection internally — the ordering hack is gone for good. Naming settled through review: `git/worktrees/` (not a flat `worktree-target`), singular `project/` with `workspace/` demoted to a sub-area (not `session/` — collides with `core/session/`), `config.ts` absorbing the state cell (no `config/` bucket, no duplicate `state.ts`). Four green commits (git-extract · merge · config-fold · docs).
