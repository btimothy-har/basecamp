# pi/ TypeScript Simplification — Analysis & Proposal

**Status:** IN PROGRESS — Passes 1, 2, 3 and parts of 5/6 shipped and green (see §Implementation status). Three items were dropped on inspection (the grep-level analysis over-stated them); the rest is deferred.
**Scope:** Behavior-preserving structural simplification of the `pi/` TypeScript extension, mirroring the Python passes merged in #290 / #291 / #292 ("simplify basecamp Python boundaries"). No feature change, no protocol-version change, no on-disk path change.
**Method:** Whole-tree audit — four parallel domain sweeps (cross-cutting primitives; `swarm`+`hub`; `project`/`session`/`git`/`model`/`ui`; the feature domains + prompt layer) plus an independent architecture map. Every finding below is line-verified; the headline items were spot-checked a second time.
**Extends/mirrors:** [repo-consolidation.md](./repo-consolidation.md) (the boundary contract), the #290/#292 Python exercise (the template).

---

## 1. The template, and how TypeScript differs

The Python exercise made three behavior-preserving moves, each a self-contained commit that stayed green (tests + ruff + file-cap):

1. **Centralize re-derived primitives** — the whole `~/.pi/basecamp` path tree → one `core/paths.py`; 5 `Console()` instances → 1; a reimplemented atomic-write → the shared one.
2. **Kill "half-registries"** — a concept re-declared by hand in every layer (model/loader/validation/porcelain) collapsed to one typed `REGISTRY` row (`ConfigSection`).
3. **Extract shared helpers** replacing dozens of call sites — `reading()`/`writing()` SQLite managers for ~66 hand-rolled `with self._connect()` sites; `ensure_column()` for 12 identical migration blocks.

**Two things are already true in TS that were the *point* of the Python work, so we don't repeat them:**

- **"core is a leaf" is enforced, not aspirational.** `scripts/check-boundaries.ts` rule 4 fails CI if core imports any other context; cross-context imports are already limited to `#core/*` (free) or `#<ctx>/index.ts`. The `core ↔ workspace` cycle that #292 untangled has no TS analogue.
- **Public surfaces are already lean.** Every domain barrel exports ≤9 symbols; there is no barrel bloat to trim. The intra-core import graph is a clean DAG with `host` as the leaf sink (one benign `agent-mode ↔ session` state/lifecycle seam).

So the TS wins are **internal**: adopt helpers that already exist but are bypassed, extract primitives that are byte-identical across files, collapse the one genuine copy-paste engine (`rpc.ts`), and build the one real half-registry (the env schema).

**Honest calibration (this matters for expectations).** Several shapes that *looked* like Python-tier half-registries are weaker in TS and are flagged as such per-item:
- `Record<AgentMode, …>` maps are **already compile-exhaustive** — adding a mode fails `tsc` until every map is filled. Collapsing them buys co-location and one edit-site, not drift-prevention.
- The `hub/protocol/` **codec is already centralized** — one generic `encodeFrame`/`decodeFrame` (`protocol/index.ts:117-138`). The design-doc backlog item "consolidate the per-family frame files" is cosmetic; there is no per-frame encode/decode to collapse. Report as confirmation, not a gap.
- The net LOC is modest (~−500 to −650). As in #290/#292, **the value is one source of truth per concept and reclaimed file-cap headroom, not line count.**

---

## 2. Headline findings

Ranked by (confidence × value). "Convergence" = independently found by more than one sweep, which is our strongest confidence signal.

| # | Finding | Sites | ~LOC | Behavior | Conf | Convergence |
|---|---------|-------|------|----------|------|-------------|
| A | `rpc.ts` request/ack round-trip copy-pasted 9× → one `requestAck` helper | 9 | −90 | preserving | HIGH | swarm/hub sweep |
| B | Canonical `getAgentDepth()`/`isSubagent()` bypassed by hand-rolled `Number(env ?? "0")` | ~14 | −15 | preserving | HIGH | **all 4 sweeps** |
| C | 7 daemon tools re-inline a 2-guard preamble; `requireAgentsSkillMessage` exists, 3/7 adopt | 7×2 | −80 | preserving* | MED-HIGH | swarm/hub |
| D | `isPathWithin` duplicated verbatim → `host/paths.ts` helper | 6–8 | −30 | preserving | HIGH | project sweep |
| E | Review/annotate TUI overlay: `showDrillDown` ≡ `showTaskCards` (~90%) | 2(+1) | −100 | preserving | HIGH | feature sweep |
| F | Agent dispatch sequence triplicated (+ a real `??`/`||` `parentSession` bug) | 3 | −60 | fix† | HIGH | **swarm/hub + feature** |
| G | Env-var typed registry — 10 of ~22 `BASECAMP_*` typed; `get/setBasecampEnv` used 0× | 15+ | −40 | see §3.4 | HIGH gap / MED rollout | primitives |
| H | Atomic JSON write/read — 3 byte-identical writers + 2 hardened + ~6 readers | ~13 | −45 | preserving‡ | HIGH/MED | primitives |
| I | `isRecord`/`isPlainObject` re-declared | 4–5 | −10 | preserving | HIGH | **primitives + project** |
| J | `completeForcedTool` — forced-tool LLM completion duplicated (bash-reviewer ↔ code-review) | 2 | −30 | preserving | MED-HIGH | feature |
| K | Worktree-namespace scattered literals → one table (genuine half-registry) | ~7 | ≈0 | preserving§ | HIGH sub / MED full | project |

\* text of 4 inline skill messages changes slightly (arguably a bugfix — 3 wrongly say "before dispatching" for wait/list).
† deliberately unifies the `parentSession` `??`-vs-`||` divergence (§3.3).
‡ the 3 identical writers are pure; the 2 hardened variants need `mode`/`exclusive` options or they regress.
§ preserving iff the three namespaces' distinct match rules are carried as per-row matchers.

---

## 3. Deep-dive on the load-bearing findings

### 3.1 The RPC round-trip — the true "SQLite-primitives" analogue (Finding A)

`createDaemonClient` (`swarm/agents/rpc.ts:131-322`) has **9 methods that hand-roll the identical round-trip**: `randomUUID()` → `connection.send({ type, request_id, … })` → `await waitForFrame(connection, ackType, f => f.request_id === id)` → re-project the ack into a hand-written object. Verified sites: `dispatchAgent`, `listAgents`, `sendPeerMessage`, `cancelAgent`, `messageStatus`, `createWorkstream`, `attachWorkstreamAgent`, `updateWorkstream`, `reviseWorkstream` (only `waitForAgents` legitimately differs — custom result-set predicate).

```ts
async function requestAck<T extends Frame["type"]>(
  connection: DaemonConnection,
  request: OutboundFrame & { request_id: string },
  ackType: T, signal?: AbortSignal,
): Promise<Extract<Frame, { type: T }>> {
  connection.send(request);
  return waitForFrame(connection, ackType,
    (f) => (f as { request_id: string }).request_id === request.request_id, signal);
}
```

Each method collapses to ~one line. Because the `DaemonClient` return types are already `Pick<…AckFrame, …>` (`rpc.ts:50-65`), the trailing re-projection objects (lines 154-157, 204-208, 218-221, 238-246, 262-267, 285-288, 299-302, 315-319) **delete entirely** — a wider ack object is assignable to the narrower `Pick`. This is the closest match to #292's `reading()`/`writing()` extraction: `rpc.ts` drops **322 → ~205 lines**, restoring cap headroom on a file that is 92% of the way to the limit.

### 3.2 Adopt the primitives that already exist (Finding B — the cleanest win)

`host/env.ts:55-62` already exports `getAgentDepth()` and `isSubagent()`. Yet `Number(process.env.BASECAMP_AGENT_DEPTH ?? "0")` (often `> 0`, i.e. a re-implemented `isSubagent`) is hand-rolled in **~14 files across 5 domains**, including **three verbatim local `isSubagent()` copies**:

`swarm/agents/types.ts:21`, `launch.ts:98`, `catalog.ts:10`; `hub/identity.ts:42`, `hub/index.ts:56`; `companion/panes/index.ts:27`, `snapshot/index.ts:101`, `herdr/metadata.ts:101`; `project/workspace/session.ts:168`; `bash-reviewer/index.ts:13,21`; `code-review/command-helpers.ts:22-25` (local copy); `tasks/tools/guards.ts:88-90` (local copy). **`browser/index.ts:4,24` already imports the helper — the reference pattern.**

All four sweeps found this independently. Behavior-preserving (`Number(x ?? "0")` and the helper agree for every input, including unset → 0). **One caveat, do not fold in:** `workstreams/herdr.ts:81-86`'s `agentDepth()` returns `1` (fail-closed) on a non-finite value — a deliberate choice that *disagrees* with core's `isSubagent()` (`NaN > 0` = false) on garbage input. Leave it.

Same "half-adopted helper" shape recurs and belongs in this pass:
- **`errorMessage`** (canonical `swarm/agents/errors.ts:1`, 14 importers) is bypassed by inline `error instanceof Error ? … : String(error)` at `dispatch.ts:104,187`, `ask.ts:87`, and duplicated outright at `model/aliases.ts:38`.
- **`requireAgentsSkillMessage`** (`support.ts:145`) is used by 3 of 7 tools; `dispatch.ts:35`, `ask.ts:37`, `wait.ts:32`, `list.ts:31` inline the string.

### 3.3 The dispatch sequence + a latent bug (Finding F)

The "build launch spec → extract `taskSpec` → build `dispatchEnv` → `dispatchWithHandleRetry`" block is triplicated: `swarm/agents/tool/dispatch.ts:113-166`, `ask.ts:71-124`, and cross-domain `code-review/command.ts:114-163`. It re-derives two primitives each time — `project: process.env.BASECAMP_PROJECT ?? "default"` (identical 3×) and `parentSession`, which is **inconsistent**: `dispatch.ts:127`/`ask.ts:83` use `BASECAMP_SESSION_NAME ?? getSessionName()?.trim() ?? …` while `command.ts:129` uses `?? (getSessionName()?.trim() || …)`. The `??`-vs-`||` split diverges when `getSessionName()` returns `""`. Consolidating into `prepareAgentDispatch()` + `resolveParentSession(pi, ctx)` in `swarm/agents/launch.ts` collapses all three and **fixes the divergence** (flag it as a deliberate micro-behavior-change, not a silent one).

### 3.4 The env-var typed registry (Finding G — the marquee half-registry)

`host/env.ts` types **10** of ~22 `BASECAMP_*` vars; `getBasecampEnv`/`setBasecampEnv` are called **zero times in production**. The 12 untyped vars (`_AGENT_ID`, `_AGENT_HANDLE`, `_REPORT_TOKEN`, `_RUN_ID`, `_RUN_ATTEMPT`, `_RUN_RESULT_PATH`, `_RUNNER_MANAGED_RESULT`, `_PARENT_SESSION`, `_SIBLING_GROUP`, `_DAEMON_UDS`, `_AGENT_TITLE`, `_REPO_ROOT`) are threaded as raw literals through 15+ files, and the same 5-name "restricted"/runner set is **re-declared as module-local constants in three files** (`run-result.ts:6-8`, `executor.ts:16-22`, `launch.ts:16-22`) — the exact #290 symptom. The fix is to make `host/env.ts` own all ~22 vars (extend the union or a typed `BASECAMP_ENV` const map), delete the three constant blocks, and have the spawn-env builders derive their key lists from the registry.

**Behavioral caveat that dictates sequencing:** `getBasecampEnv` coerces `"" → undefined`; many raw reads use `?? "0"` or `|| null` and treat empty-string differently. So this pass **splits in two**: (1) the strictly-safe half — delete the three constant blocks, type the names, route the depth reads (already covered by Finding B) — ships first; (2) migrating the string-var *reads* through the typed getter requires a per-site empty-string audit and ships as a careful follow-up.

---

## 4. Proposed passes

Each pass is an independently-shippable commit/PR that holds the full gate green — `npm run check` (tsc + biome + boundaries + file-length ≤350) and `npm test` (per-domain `.test.ts` globs, strict Node, explicit `.ts` imports), plus ruff + pytest in CI. Ordered safest-and-highest-ROI first. New modules follow the boundary rules (cross-domain only via `#<ctx>/index.ts`; `#core/*` free).

**Pass 1 — Adopt the helpers that already exist (zero new abstraction).**
Findings B + the `errorMessage`/`requireAgentsSkillMessage` adoptions. Route ~14 depth sites, 3 `isSubagent` copies, 4 `errorMessage` inlines/1 dup, and 4 inline skill strings through primitives that already ship. Spans 5 domains; near-zero risk; immediate legibility. *Net ~−35.*

**Pass 2 — Extract the byte-identical host primitives.**
Findings D (`isWithin`/`isStrictlyWithin` → `host/paths.ts`, 8 copies), I (`isRecord` → one `host` util), H-safe (the 3 byte-identical `writeJsonFileAtomic` writers + `readJsonFile`), `sleep`/`FLUSH_DELAY_MS` (×3 → `host`), and the path-tree leaves (§ below). All host-level, all behavior-preserving. The 2 perms-hardened writers fold in via `{ mode, exclusive }` options as a checked sub-step. *Net ~−80.*

**Pass 3 — The RPC/dispatch collapse (the headline).**
Findings A (`requestAck`, −90), C (`guardAgentsTool` preamble, −80), F (`prepareAgentDispatch` + `resolveParentSession`, −60, fixes the bug). Highest LOC win and the truest match to the Python exercise; sequenced after the pure wins because it touches the dispatch hot path. *Net ~−200.*

**Pass 4 — The env-var registry (Finding G).**
Safe half only in this pass: own all vars in `host/env.ts`, delete the three re-declared constant blocks, derive spawn-env key lists from the registry. String-var read migration deferred to a per-site audit follow-up. *Net ~−40.*

**Pass 5 — Feature-domain de-duplication.**
Findings E (`feedbackReviewOverlay`, −100 — also resolves `review/index.ts`'s 277-line near-cap), J (`completeForcedTool`, −30), the Herdr eligibility predicate (3 gates → 1), and `renderIndexedTaskCall` (4 → 1). Each independently shippable. *Net ~−160.*

**Pass 6 — Registry co-locations + near-cap splits (structural, lower-urgency).**
Finding K (worktree-namespace table, hosted in a new `git/worktrees/labels.ts` that also relieves `crud.ts`), the agent-mode metadata registry (framed honestly as co-location — medium value), the `resolution.ts` parse sub-helpers (preserve the test-pinned divergence), tilde-expand + aliased-model helpers, and the real split-seams: `support.ts` (grab-bag → `params`/`list-view`/`format`), `launch.ts` (extension-tool discovery → `extension-tools.ts`), `ui/footer.ts` (fs-watch branch reader → `branch-watcher.ts`), `project/config.ts` (→ `resolve.ts`). Plus the compile-time `Frame` exhaustiveness guard (no LOC; turns runtime-test drift-detection into a `tsc` error). *Net ≈0 LOC; moves lines, buys cap headroom + legibility.*

---

## 5. Deliberately out of scope / declined

Stated explicitly so a later pass doesn't chase them:

- **`hub/protocol/` codec** — already at the target state (generic `encode/decodeFrame`; `FRAME_TYPES` is a load-bearing runtime array TS cannot derive from the union). The doc-backlog "consolidate frame files into base/agents/broker" is a cosmetic regroup with no dedup payload; skip or do purely for tidiness.
- **`exec`/`spawn` unification** — `pi.exec` (cwd injection) vs detached daemon spawn vs streaming BigQuery capture are genuinely different execution models. Only real overlap is intra-`bigquery` (a same-file refactor).
- **User notification** — `ctx.ui.notify` is already the single primitive at ~60 sites. No work.
- **Footer's sync branch reader vs `git/repo.ts`** — footer needs *sync* fs access to seed an `fs.watch`; repo.ts is async over `pi.exec`. Justified duplication.
- **The "three-daemon" wire overlap** (repo-rearchitecture §250) — now **Python-only**; companion is a pure snapshot-file consumer with no `#core/hub` edge. Not a TS win.
- **`scratchDir`/`timestampForFile` dedup** (repo-rearchitecture §330) — **moot**: the second consumer vanished when browser moved to the Playwright CLI skill; `timestampForFile` has one caller left.
- **String-var reads through `getBasecampEnv`** — behavior-sensitive (empty-string coercion); deferred to a per-site audit (§3.4).
- **Full `Frame` → runtime registry** — TS can't materialize the runtime `FRAME_TYPES` array from the union; a compile-time exhaustiveness guard (Pass 6) is the whole available win.

## 6. Already at target — positive controls (do not "fix")

These embody the pattern the findings above are reaching for; touching them would be churn:
- **`session/state/`** — one `processScoped` cell, one schema interface + matching validator, a single generic `updateCurrentSessionState(updater)`. No per-field boilerplate.
- **Copilot `plan()`-hiding** — `isCopilotMode` + `PLAN_TOOL_NAME` single-owned in `agent-mode/copilot.ts`, consumed by both enforcement layers. (Note: AGENTS.md's "workspace capabilities filter" phrasing is stale — the filter lives in `system-prompt/prompt.ts:158`; worth a one-line doc fix.)
- **`code-review`** — the `REVIEWERS` table + `SEVERITY_RANK` + deterministic `mergeFindings`/`computeVerdict` are the good registry shape to emulate.
- **`system-prompt`** — cleanly layered and registry-driven via `context-builders.ts`; no duplicated layer assembly.
- **Naming/slug** — centralized in `git/worktrees/target.ts` + `naming/`; consumers already delegate.
- **The boundary contract itself** — core-is-a-leaf and the ≤9-export barrels are already enforced/clean.

---

## Appendix — path-tree leaves (the §3 primitive, detail)

Domains correctly import `basecampRoot`/`basecampConfigPath` from `host/paths.ts`, but each spells its own `~/.pi/basecamp/<leaf>` subdir at point-of-use: `system-prompt/prompt.ts:24,28` (`prompts`, `styles`), `tasks/lifecycle/store.ts:10` (`tasks`), `companion/snapshot/model.ts:11` (`companion/snapshots`). `git/constants.ts:4` (`~/.worktrees`) and `swarm/agents/executor.ts:13` (`tmpdir`) are **intentionally separate roots** — name them in the tree for legibility, do not reparent. Centralizing the leaves in `host/paths.ts` mirrors the Python `core/paths.py` move; it is a pure `path.join` move (behavior-preserving) with a genuine cohesion tradeoff (co-locating a subdir name with its domain is defensible), hence framed as *moderate*, folded into Pass 2.

## Implementation status

Shipped as independent, green, behavior-preserving commits (each holds `npm run check` + `npm test`; the core four were adversarially cross-checked by three reviewers and found clean):

- **Pass 1 — adopt existing helpers.** `getAgentDepth`/`isSubagent` (~14 sites + 3 local copies), `errorMessage` inline coercions, and the four skill-gate strings via `requireAgentsSkillMessage` (fixing `wait_for_agent`'s inaccurate message). ✅
- **Pass 2 — home the primitives.** `isWithin`/`isStrictlyWithin` → `host/paths.ts` (6 copies); new `host/files.ts` (`isRecord` ×6, `writeJsonFileAtomic` ×3, `readJsonFile`) + test; `errorMessage` → `core/errors.ts` (deep `swarm/agents/errors.ts` deleted); `sleep` → `core/async.ts`. ✅
- **Pass 3 — RPC round-trip.** `requestAck()` collapses the 8 request/ack methods (rpc.ts 322→299); `resolveParentSession()` unifies the `??`/`||` inconsistency (a real latent bug). Projections were **retained** — returning the raw ack leaks frame fields, which the daemon-client tests correctly caught. ✅
- **Pass 5a — `renderIndexedTaskCall`.** 4 identical task renderCalls → 1. ✅
- **Pass 6 (partial) — model-ref parse/lookup.** `parseProviderModelRef` + `findModelByExactId`, preserving the test-pinned fallthrough divergence. ✅

**Dropped after inspection — the analysis over-stated these (no clean dedup exists):**

- **Pass 4 (env registry).** The "restricted set re-declared in 3 modules" is false: it lives in one place (`executor.ts`); the run-result name constants are already shared (defined once, imported); `launch.ts:16-22` is tool names, not env vars. Extending the typed union to all vars is pure churn with empty-string-coercion risk.
- **Herdr eligibility gate (Pass 5).** `shouldOpenWorkstreamInHerdr` returns granular per-check *skip-reasons*, so it can't delegate to a single shared boolean; only the two companion predicates return plain bools. Forcing a shared helper would muddy the reason-logic for ~no gain.
- **`completeForcedTool` (Pass 5).** bash-reviewer's `parseGateResponse`/`resolveGateToolChoice`/`resolveGateReasoningEffort` are extensively, independently tested; extraction would either duplicate that logic or require restructuring the gate test suite — net-negative.

**Deferred (genuine, but wants dedicated care):**

- **Review/annotate TUI overlay (Pass 5).** `showDrillDown` ≡ `showTaskCards` really are ~90% identical (~−100 LOC) — the single biggest remaining dedup. But it's a configurable *interactive* `ctx.ui.custom` component with **no unit-test coverage**, so a subtle input/render regression wouldn't be caught. Do it with a dedicated overlay test harness.
- **Pass 6 remainder.** Worktree-namespace table (+ `crud.ts` split), and the near-cap file splits (`ui/footer.ts`, `swarm/agents/tool/support.ts`, `swarm/agents/launch.ts`, `project/config.ts`) — low-risk structural moves, no file is currently over the 350 cap so this is proactive headroom. The agent-mode metadata registry is low value (the `Record<AgentMode,…>` maps are already compile-exhaustive — co-location only).

The through-line: the clean wins were *adoption* and *byte-identical extraction*; most of the remaining "half-registries" dissolve into legitimate structural differences on close reading — a caution worth carrying into similar exercises.

---

*Analysis produced by a four-way parallel audit; all file:line references verified against the tree at the branch head. Implementation status updated after Passes 1–3/5a/6-partial shipped.*
