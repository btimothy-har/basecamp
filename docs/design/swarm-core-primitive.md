# Swarm as a Core Primitive — Design

**Status:** BUILT (green `npm run check` — 9 contexts, 485 files — + full TS suite, 705 tests) · **Scope:** Dissolve the `pi/swarm/` TypeScript domain. The agent-dispatch *runtime* relocates **wholesale** into a core adapter — **`pi/core/swarm/`**, a peer of `pi/core/hub/` — with its `agents/` internals left intact (no resplit this pass). Its two applications, `/code-review` and workstreams, graduate to **standalone feature domains** (`pi/code-review/`, `pi/workstreams/`) that consume `#core/swarm`. Relocation-only — no behavior, protocol, or wire change; the on-disk path and the Python `basecamp.hub.swarm` package are untouched. · **Extends:** [async-agents.md](./async-agents.md) (the runtime), [hub-core-connector.md](./hub-core-connector.md) (the connection → core). · **Refines:** [hub-core-connector.md](./hub-core-connector.md) §6 — its "swarm remains a domain/plugin" call correctly kept the *features* out of core but bundled the *primitive* in with them; this pass separates the two.

This is the next structural pass on the async-agent stack, and the one that finishes the arc. Prior passes fixed *packaging* (consolidation), *navigability* (rearchitecture), the *analysis data plane* (companion daemon-broker), and *connection ownership* (hub-core-connector). This pass fixes *primitive ownership*: it recognizes that dispatching an agent has become a **shared substrate** the rest of basecamp builds on, and moves that substrate to the center of the star — while the things built on it become first-class features.

---

## 1. Problem statement

The hub-core-connector pass hoisted the daemon *connection* into `#core/hub` and correctly reframed `swarm` as "the agent plugin." But it left an inverted structure underneath. `pi/swarm/agents/` is really two things fused into one domain:

- **A runtime primitive** — dispatch / wait / ask / cancel / peer-message an agent, plus the client, launch-spec builder, run reporter, tools, and observability. ~2,900 LOC.
- **Two applications of that primitive** — `/code-review` (dispatches six reviewer agents) and workstreams (durable coordination over agent sessions).

And the applications are nested *inside* the same domain as the primitive they consume: `review/` lives at `pi/swarm/agents/review/`, workstreams at `pi/swarm/workstreams/`. Neither `import #swarm` — they *are* `pi/swarm/`.

That nesting hides the defining signal. "We keep building on the agent runtime" is exactly the fact that, in a clean graph, shows up as `feature → substrate` edges. Because the features are nested, those edges are invisible: the dependency graph shows `swarm` as a leaf that nothing depends on, when in reality it is a platform with two tenants.

Two forces make this the moment to correct it:

- **The primitive is proliferating consumers.** Review and workstreams today; more agent-powered capabilities are planned. Each new one must either nest inside `swarm` (regrowing the grab-bag) or become its own domain that imports the runtime.
- **A domain that imports the runtime breaks the star.** [repo-rearchitecture.md](./repo-rearchitecture.md) converged on a single-hub star — every feature depends on **core**, not on other features (the lone blessed exception being `companion → tasks`). The instant `code-review` and `workstreams` become domains importing `#swarm`, swarm is a **second hub**: a feature-node that other feature-nodes depend on. The star's own rule answers where that shared node belongs — **core**.

## 2. The insight — separate the primitive from its applications

"Swarm is becoming core" is true, but only of *one layer* of swarm. There is a primitive and there are applications:

- **The agent-dispatch primitive** — spawn/wait/ask/cancel/message an agent, the client over the hub connection, the launch spec, run reporting, the tools, the observability views + widget, the agent catalog. This is substrate, in exactly the sense `#core/hub` (the connection) is substrate.
- **Review and workstreams** are *applications* — features that happen to be the primitive's first two customers. Their policy (verdict rules, workstream lifecycle) does not get more "core" just because the thing underneath them does.

This dissolves the tension in §1's second bullet. The "standalone swarm that code-review/workstreams import" shape and "the primitive lives in core" shape have the **same feature topology** — the two features as domains consuming the agent primitive. They differ only in *where the primitive sits*: a feature-node (`#swarm`, which breaks the star) versus the center (`#core/swarm`, whose edges are the blessed ones). Putting the primitive in core is simply the star-preserving placement of the same decomposition.

It also **refines rather than reverses** [hub-core-connector.md](./hub-core-connector.md) §6, which rejected "fold swarm into core" on the grounds that "swarm is genuine feature breadth … not framework plumbing." That was right about the *features*. It only erred by treating the primitive and the features as one indivisible thing. Split them, and the primitive is plumbing (→ core) while the breadth stays breadth (→ feature domains).

## 3. Goals and non-goals

### Goals

- **A `pi/core/swarm/` adapter** owns the agent-dispatch primitive, a peer of `core/hub`/`core/git`/`core/host`/`core/model`. It keeps the existing `agents/` runtime **as-is** (wholesale relocation), imports `#core/hub` for the pipe, and is registered by `registerCore`.
- **`code-review` and `workstreams` become standalone feature domains** (`pi/code-review/`, `pi/workstreams/`), each depending only on `#core/*`. `pi/swarm/` is removed.
- **The star is preserved.** Every domain imports core and nothing else; `core` still imports no feature domain.
- **Green at every step.** Relocation-only, each tranche `make lint` + `make test`-green (§8). Minimal churn to the agent internals — the point of this pass is the core/feature *boundary*, not an internal reorg.

### Non-goals

- **No internal resplit of the runtime this pass.** The `agents/` grab-bag keeps its current flat shape; giving it `catalog/client/launch/reporting/tools/observability` substructure is a **deferred follow-up** (§10), done later inside `core/swarm/` where it no longer entangles the boundary move.
- **No behavior, protocol, or wire change.** `PROTOCOL_VERSION` stays; frames are byte-identical; ACL, run lifecycle, and collaboration semantics are unchanged.
- **No on-disk or Python rename.** The runtime dir stays `~/.pi/basecamp/swarm/`; the daemon package stays `basecamp.hub.swarm`. The `#core/swarm` name deliberately mirrors the Python `hub/swarm`.
- **No catalog-definitions move.** The catalog *registry* is already core (`#core/catalog`); the agent *definitions* (`builtin/*.md`) ride along inside `core/swarm/agents/` as the primitive's standard library — see §5.
- **No Python-daemon-internal rework** (`runner.py`, `app.py`) — server-side, orthogonal to TS ownership.

## 4. Target structure

### 4.1 `pi/core/swarm/` — the dispatch primitive (from `pi/swarm/agents/`, wholesale)

`pi/swarm/agents/` moves verbatim to `pi/core/swarm/agents/` — same files, same internal (relative) imports, no restructuring. Only the domain-level path and the register wiring change.

```
pi/core/swarm/
  index.ts          registerSwarm — agent catalog provider + session surfaces (from pi/swarm/index.ts's runtime half + agents/surfaces.ts)
  agents/           the runtime, relocated intact: catalog · client/rpc · delivery · dispatch-retry ·
                    launch · executor · model-resolution · run-result · reporter · event-summaries ·
                    tools + tool/ · widget · view/ · discovery · builtin/*.md · types · errors
  skills/           the `agents` skill (from pi/swarm/skills/)
```

`core/swarm` imports only `#core/*` (`hub`, `model`, `project/workspace`, `skills`, `catalog`, `host`, `global-registry`) — all intra-core. It defines no frame type and opens no socket; it calls `#core/hub`. Consumers reach it as `#core/swarm/agents/…` — an ordinary `#core/*` deep path (no new alias needed; `#core/*` already covers it).

### 4.2 `pi/code-review/` — a feature domain (from `pi/swarm/agents/review/`)

`/code-review`, unchanged in behavior. Consumes `#core/swarm/agents/*` (client, launch, dispatch-retry, discovery, errors) and `#core/host` (the ex-`extension-root`). Its eight internal modules move verbatim; only the `../` runtime imports repoint to `#core/swarm/agents/…`.

### 4.3 `pi/workstreams/` — a feature domain (from `pi/swarm/workstreams/`)

Unchanged in behavior. Its coupling to the runtime is already minimal — `agents/client.ts` (6 sites) and `agents/errors.ts` (3) — both of which become `#core/swarm/agents/…`. The `pi --workstream` startup and the three tools move as-is.

### 4.4 The stray

- **`extension-root.ts` → `#core/host/paths.ts`.** A generic "extension package root" helper with zero agent specificity, and depth-coupled (`../../../..` hardcodes its directory depth) — the relocation *changes* that depth, so it would break in place. It lands beside `piRoot`/`basecampRoot`, in a core file that doesn't move. (`errors.ts` stays inside `core/swarm/agents/` and rides the wholesale move — it is consumed by both feature domains from there.)

### 4.5 The register split

`registerCore` grows one call — `registerSwarm(pi)` — which does what `swarm/index.ts` did for the runtime: register the agent catalog provider and the session surfaces (the `isTopLevel` / `isDaemonSpawnedAgent` tool + reporter + widget + delivery wiring). `extension.ts` drops `["swarm", registerSwarm]` and adds `["code-review", registerCodeReview]` and `["workstreams", registerWorkstreams]`. Core registers first (already true), so the primitive exists before either feature registers; tools resolve the connection lazily regardless.

This also removes the last non-core catalog provider: after the move, `core` registers the tools, skills, **and** agents providers — all three capability types are core-registered, feature domains just supply content via the primitive.

## 5. The core/feature seam — what is primitive, what is feature

The cut this pass makes is coarse and deliberate: **everything currently under `pi/swarm/agents/` except `review/` is the primitive (→ `core/swarm`); `review/` and `workstreams/` are the applications (→ their own domains).** No file's *responsibility* is reclassified — the runtime moves as a unit.

| Piece | Verdict | Why |
|---|---|---|
| client · launch · reporting · tools · observability · catalog · types · errors | **core/swarm** | The dispatch primitive and its standard content — substrate, like `#core/hub` is. Moves wholesale. |
| `review/*` | **`pi/code-review/`** | An application: dispatches reviewer agents, owns verdict policy. |
| `workstreams/*` | **`pi/workstreams/`** | An application: durable coordination policy over agent sessions. |
| `extension-root` | **core/host** | Not agent-specific; a depth-fragile path helper that breaks on the move (§4.4). |

The catalog note stands: the *registry* is `#core/catalog`; the *definitions* (`builtin/*.md`) are the primitive's standard library and ride along — core can't enumerate them (agents aren't pi-native), so the provider ships with the code. The `DaemonClient` seam from hub-core-connector holds unchanged — frame *types* + transport are `#core/hub`; the client that *builds* frames is now under `#core/swarm`, still one level up from the pipe.

## 6. Decisions & rejected alternatives

| Decision | Chosen | Rejected |
|---|---|---|
| Primitive home | **`pi/core/swarm/`** — a core adapter peer to `core/hub` | *Fold into `#core/hub`*: conflates "the pipe" with "the agent system on the pipe" and bloats hub. `core/swarm` imports `core/hub`, keeping hub thin. |
| Primitive name | **`swarm`** — product-specific, mirrors Python `hub/swarm` | *`agents`*: more generic but drops the established product name that the daemon + on-disk path keep. |
| Feature placement | **Standalone domains** `pi/code-review/` + `pi/workstreams/` on `#core/swarm` | *Keep them bundled under a slim `swarm` domain*: preserves a vestigial grouping with no dependency justification (they don't import each other) and keeps `swarm` alive for no reason. |
| Review domain name | **`code-review`** — matches the `/code-review` command | *`review`*: too generic for a top-level domain. |
| Whole-swarm-into-core | **No** — only the primitive; features stay features | *Move all of `swarm` into `core`*: mechanically possible (swarm imports only core) but puts feature policy in core and creates "why is code-review core but the next feature isn't?" |
| Star vs second hub | **Primitive → core** (blessed edges) | *`swarm` standalone as a feature-node that the features import*: same topology, but the shared node is a feature → breaks the single-hub star (§2). |
| Scope | **Wholesale relocation only**; internals untouched | *Relocate + resplit the grab-bag now*: couples a risky internal reorg to the boundary move. Split later, inside `core/swarm` (§10). |

## 7. Boundary & invariant impact

- **`CONTEXTS` (check-boundaries.ts):** remove `swarm`; add `code-review`, `workstreams`. `swarm` is **not** re-added as a context — it now lives inside `core` as `#core/swarm/*` (a deep path, like `#core/hub`).
- **`core` still imports no feature domain.** The moved runtime imports only `#core/*` (verified: `pi/swarm` has zero non-core cross-domain imports today). `#core/swarm/*` is core-owned code.
- **Subpath aliases (package.json):** delete `#swarm/*`. Add `#code-review/*` and `#workstreams/*`. **No alias for `core/swarm`** — the existing `#core/*` → `./pi/core/*` already resolves `#core/swarm/…`.
- **Test glob (package.json):** drop `pi/swarm/**/*.test.ts`; add `pi/code-review/**/*.test.ts` and `pi/workstreams/**/*.test.ts`. `#core/swarm` tests are covered by the existing `pi/core/**/*.test.ts` glob.
- **Skills path (package.json):** `./pi/swarm/skills` → `./pi/core/swarm/skills`.
- **Surviving state keys are stable.** `processScoped("basecamp.swarm.agentConnect", …)` and the daemon-client key are string-keyed, location-independent — `/reload` survival is preserved (keys unchanged even though "swarm" no longer names a TS *domain*).
- **`biome.json` / linter-blind paths:** re-anchor any `pi/swarm` exclude; the protocol-parity test already points at `#core/hub/protocol` (untouched here).

## 8. Migration sequencing (green at every step)

Relocation-only, `git mv`-shaped, each a `make lint` + `make test`-green commit. Ordered so the star is never broken — the primitive reaches core before the features graduate.

1. **The stray → core.** `extension-root.ts` → `core/host/paths.ts`; repoint its two importers (`surfaces`, `review/command`). Green. *(Standalone; also fixes the depth-fragility before the move would trip it.)*
2. **Relocate the runtime wholesale.** `git mv pi/swarm/agents → pi/core/swarm/agents` (review rides along on its relative imports); add `pi/core/swarm/index.ts` (`registerSwarm`, from `pi/swarm/index.ts`'s runtime half); `registerCore` calls it; delete the `#swarm/*` alias; repoint `workstreams`' `../agents/*` imports to `#core/swarm/agents/*`. Green.
3. **Graduate code-review.** `pi/core/swarm/agents/review/` → `pi/code-review/` with `index.ts` (`registerCodeReview`); repoint its `../*` imports to `#core/swarm/agents/*` + `#core/host`; add the `#code-review/*` alias + test glob + `CONTEXTS` entry; `extension.ts` registers it. Green.
4. **Graduate workstreams.** `pi/swarm/workstreams/` → `pi/workstreams/`; move `pi/swarm/skills/` → `pi/core/swarm/skills/` and update the skills path; add `#workstreams/*` alias + glob + `CONTEXTS`; `extension.ts` registers it. `pi/swarm/` is removed. Green.
5. **Doc truing** (§11).

Steps 1–2 deliver the headline (the primitive is core, the star's shared node is central); 3–4 graduate the features; each is independently revertable.

## 9. Risks

- **Dissolves a domain, adds a core adapter, and creates two domains.** Mitigated by the verified facts that keep the surface small: `swarm` imports only `#core/*`; `code-review` and `workstreams` are mutually independent; and *only* `extension.ts` imports `#swarm`, so the external contract is one file.
- **The wholesale `git mv` touches every in-`agents/` import site's *domain* path** — but the *relative* imports inside `agents/` are untouched (that's the point of moving it as a unit), so the change is the `#swarm`→`#core/swarm` repoint in the two feature domains plus the alias/glob updates. Caught by `tsc` whole-graph + the boundary check + the suites at each green step.
- **Registration ordering.** `registerSwarm` (catalog provider + surfaces) must run before `system-prompt` reads the catalog and before feature registration — `extension.ts`'s core-first order already guarantees it.

## 10. Deferred — future / at execution

- **The internal substructure resplit.** Once the runtime is `core/swarm/agents/`, give the flat grab-bag its responsibility subdirs (`catalog/client/launch/reporting/tools/observability`), as originally motivated. Deferred out of this pass to keep the boundary move low-risk ("don't disturb the agent internals yet").
- **Reviewer-specialist definitions.** The `*-specialist` builtin agents are `code-review`-coupled; the generic ones (`worker`, `scout`) are the primitive's standard library. A later pass may split the review-specific definitions into `pi/code-review/`, leaving only generic agents in `core/swarm/agents`.
- **Inherited, still deferred:** protocol single-source-of-truth / codegen; the third (Python companion) daemon client; the on-disk `~/.pi/basecamp/swarm/` → `…/hub/` rename; Python `runner.py`/`app.py` internals (all from [hub-core-connector.md](./hub-core-connector.md) §10).

## 11. Doc truing (at execution)

- **AGENTS.md** — Repo Map: the `swarm/` row splits into `core/swarm` (the primitive) + `code-review/` + `workstreams/`; the Extension-Modules, Code-Review, and Workstreams sections re-home from "swarm domain" to their new owners; the composition-order list swaps `swarm` for `code-review` + `workstreams`.
- **`pi/core/README.md`** — add the `swarm/` adapter beside `hub`/`git`/`host`/`model`.
- **New `pi/code-review/README.md` + `pi/workstreams/README.md`**; **relocate `pi/swarm/README.md`** into `pi/core/swarm/` (reframed as the primitive).
- **This doc + [async-agents.md](./async-agents.md) / [hub-core-connector.md](./hub-core-connector.md)** — cross-links; note that §6's "swarm stays a plugin" is refined here (primitive → core, features → domains).

## 12. Execution status

Built as a green sweep (`npm run check` — 9 contexts, 485 files — + the full TS suite, 705 tests) on this branch, in the §8 order with one deviation: steps 2–4 landed together, because the `pi/swarm/index.ts` entrypoint split across three owners and a transitional shim would have been pure throwaway.

- **Step 1** — `extension-root.ts` → `core/host/paths.ts`, reimplemented as a `package.json`-anchored upward walk. This also *fixes* a latent overshoot: the old `../../../..` resolved to the repo's **parent**, harmless only because everything real lives under the repo.
- **Steps 2–4** — `git mv pi/swarm/agents → pi/core/swarm/agents`; `review/ → pi/code-review/`; `workstreams/ → pi/workstreams/`; `skills/ → pi/core/swarm/skills/`; `pi/swarm/` removed. New `registerSwarm` (called by `registerCore`) + `registerCodeReview` + `registerWorkstreams` (registered by `extension.ts`). `#swarm/*` alias deleted; `#code-review/*` + `#workstreams/*` added; `CONTEXTS`, test globs, and the skills path retargeted. **The one non-obvious cost:** moving the runtime into `core` made its ~35 `#core/*` imports *same-context*, which the boundary checker requires be **relative** — all converted to depth-correct relative paths (`#core/hub/index.ts` → `../../hub/index.ts`, etc.).
- **Step 5** — doc truing (this §, AGENTS.md, `pi/core/README.md`, the relocated `core/swarm` README, new `code-review` + `workstreams` READMEs, the `tasks` README cross-ref).

Retained per the non-goals: the Python `basecamp.hub.swarm` package, the `~/.pi/basecamp/swarm/` on-disk path, the companion dashboard's `#swarm-*` Textual widget IDs, and the deferred internal grab-bag resplit (§10).
