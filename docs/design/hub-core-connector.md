# Hub as Core Connector — Design

**Status:** COMPLETE · all five steps SHIPPED (protocol, connector, and `report-thread` in `pi/core/hub/`; `companion→swarm` dissolved; docs trued; `agents/daemon/` flattened) — green `make lint` + full TS suite (704) + Python suite (463) at each commit · **Scope:** move the hub-daemon *connector* (transport + wire protocol + ensure-daemon + node identity) out of `pi/swarm/` and into a core-owned `pi/core/hub/` adapter, so every Pi session plugs into the hub through core and `swarm` becomes an ordinary plugin that consumes it. Ownership/relocation only — no behavior, protocol version, or on-disk path change. · **Extends:** [async-agents.md](./async-agents.md) (the daemon), [companion-daemon-broker.md](./companion-daemon-broker.md) (hub as per-session broker) · **Realizes/supersedes:** [repo-rearchitecture.md](./repo-rearchitecture.md) §6.2's deferred "daemon hoist" — but to core, not swarm-internal.

This is the design record for the next structural pass on the async-agent stack. Prior passes fixed *packaging* (consolidation), *navigability* (rearchitecture), and the *analysis data plane* (companion daemon-broker). This pass fixes *ownership*: it makes the TypeScript side reflect what the Python side and the runtime already are — **hub is the central command center; the connection to it is core infrastructure; swarm is one plugin among several that ride on it.**

---

## 1. Problem statement

The hub daemon began life as the async-agent coordinator, so its client — the WebSocket transport, the frame codec, ensure-daemon, and node-identity derivation — was built inside `pi/swarm/agents/daemon/` (39 files, ~4,100 LOC, 57% of all swarm TS). That was correct when swarm was the only consumer.

It no longer is. Two things changed underneath that placement:

- **The connection went universal.** The companion daemon-broker ([companion-daemon-broker.md](./companion-daemon-broker.md) §9) promoted the daemon "from async-agent coordinator to observation broker for **every** primary session." Every top-level session now opens the hub connection at `session_start` to ship its thread — whether or not it ever dispatches an agent.
- **A second domain reached in.** Companion now imports `reportThread` from `#swarm/index.ts` (re-exported from `pi/swarm/agents/daemon/report-thread.ts`). This gave the dependency graph a **second non-core inter-feature edge** (`companion→swarm`), on top of the intended `companion→tasks`; the "single hub (core)" star that [repo-rearchitecture.md](./repo-rearchitecture.md) §post-execution converged on has quietly drifted.

So the connector is now a shared, session-universal dependency living inside a feature domain, with another feature domain importing that domain to reach it. That is exactly the shape the rearchitecture assigns to **core**: §6.1 established that "core owns the shared low-level adapters (git/worktree, exec/spawn, env, the model provider), so most domains have no adapter of their own." The hub connection was the lone adapter that stayed in a feature — justified only while swarm was its sole consumer. That justification is gone.

## 2. The insight: Python is already hub-centric; the TS side is inverted

The Python daemon was reorganized by the `hub-untangle` work into a hub core with two sub-domains. The TypeScript extension never made the matching move — it still keeps everything, including the connection handshake and companion's own `thread_report` frame, inside `swarm`:

| Concern | Python (`src/basecamp/hub/`) | TypeScript (today) | TypeScript (target) |
|---|---|---|---|
| Connection handshake — `register`/`registered`/`error` + `PROTOCOL_VERSION` | `hub/frames/__init__.py` + `version.py` — **hub core** | `pi/swarm/agents/daemon/frames/` — inside swarm | `pi/core/hub/protocol/` — **core** |
| Companion analysis — `thread_report` | `hub/frames/broker.py` — **hub/broker** | `pi/swarm/…/frames/thread-report.ts` — inside swarm (companion reaches in via `#swarm`) | `pi/core/hub/protocol/` — **core** |
| Agent frames — dispatch/wait/peer/cancel/workstream… | `hub/frames/swarm.py` — **hub/swarm** | `pi/swarm/…/frames/` — inside swarm | `pi/core/hub/protocol/` — **core** (defs) |
| Transport + ensure-daemon + identity | folded into `hub/` core | `pi/swarm/agents/daemon/` | `pi/core/hub/` — **core** |
| Agent tools · run reporting · review · workstreams | `hub/swarm/` | `pi/swarm/agents/` | `pi/swarm/` — **plugin** |

Python already *is* "hub core + `hub/swarm` + `hub/broker`." The repivot is: **make the TS extension mirror it** — `pi/core/hub` ⟷ `hub/` core, `pi/swarm` ⟷ `hub/swarm`, `pi/companion` ⟷ `hub/broker`.

## 3. Goals and non-goals

### Goals

- **Core owns the hub connector.** A new `pi/core/hub/` adapter owns the WS transport, the frame codec + all frame type definitions, ensure-daemon (spawn/health/version handshake), node-identity derivation, and the connection-status surface. `registerCore` establishes the connection at `session_start`.
- **Swarm becomes a plugin.** `pi/swarm/` keeps the agent client methods, dispatch/ask/cancel/wait/list/peer tools, run reporter, active-agents widget, run/workstream observability views, review, and workstreams — all consuming `#core/hub`. It contributes *logic and tools*, not transport or wire ownership.
- **Restore the clean core-star.** `companion` imports the connector and `reportThread` from `#core/hub` (a free `→core` edge); the `companion→swarm` edge is deleted. Companion's only remaining non-core edge is the intended `companion→tasks`.
- **Green at every step.** Relocation-first, each step `make lint` + `make test`-green (§8).

### Non-goals

- **No protocol single-source-of-truth / codegen this pass.** The three hand-maintained copies (TS types, Python Pydantic, JSON fixtures) stay as-is. Giving the protocol one home (core) is the *enabler* for SSOT; doing the codegen is a **future move** (§10).
- **No Python-daemon-internal rework.** `runner.py`'s attempt proxy and `app.py`'s frame router (the deepest complexity, per the swarm audit) are untouched — they live server-side and are orthogonal to TS ownership.
- **No behavior, protocol, or wire change.** `PROTOCOL_VERSION` stays 20; frames are byte-identical; no new/removed frames; ACL, run lifecycle, and collaboration semantics are unchanged.
- **No on-disk path rename.** The runtime dir stays `~/.pi/basecamp/swarm/` (the documented legacy-retained path); this pass does not touch it.
- **No companion feature-cleanups.** `diff.py` split, `store/` flattening, and the small companion renames from the audits are separate follow-ups (§10).

## 4. Target structure

### 4.1 `pi/core/hub/` — the connector (core's hub-daemon adapter)

Everything whose job is to *speak to the hub*, grouped as a core adapter alongside `core/git`, `core/host`, `core/model`:

```
pi/core/hub/
  index.ts            registerHubConnection — session_start connect + session_shutdown teardown;
                      exports awaitDaemonConnection / getActiveDaemonConnection  (surviving state)
  connection.ts       WS connect + register handshake + version gate            ← from agents/daemon/
  identity.ts         deriveDaemonIdentity + node_id/handle/role/session_file    ← teased from daemon/index.ts
  ensure.ts           ensureDaemon: health ping → spawn/restart → wait-healthy   ← spawn.ts + process.ts
  paths.ts            resolveDaemonPaths (socket/db/agents dirs)                 ← from agents/daemon/
  handles.ts          buildDeterministicAgentHandle                             ← from agents/daemon/
  http.ts             requestJsonOverUds (generic UDS HTTP helper)              ← from agents/daemon/
  status.ts           publishDaemonStatus (connection health → UI)              ← from agents/daemon/
  report-thread.ts    reportThread transport + thread_report frame (broker)     ← from agents/daemon/
  protocol/           the wire contract: codec + ALL frame type defs + fixtures
    index.ts          encodeFrame/decodeFrame · Frame union · FRAME_TYPES        ← frames/index.ts
    version.ts  base.ts  agents.ts  broker.ts   frame types by concern           ← frames/*.ts, regrouped
    frames/*.json  PROTOCOL.md                                                   ← pi/swarm/protocol/
```

Import surface for other domains: `#core/hub/index.ts` (connection accessors + `reportThread`) and `#core/hub/protocol/index.ts` (frame types + codec). Both are ordinary `#core/*` deep paths — freely importable, no new alias.

### 4.2 `pi/swarm/` — the plugin

What remains is the *agent system built on the connection*:

```
pi/swarm/
  index.ts            registers agent catalog, agent surfaces, review, workstreams
  agents/
    client.ts         createDaemonClient — the agent request methods (dispatch/wait/ask/cancel/
                      peer/message-status/list/fetchRunSummary), built on #core/hub connection + frames
                                                                                ← rpc.ts, renamed
    dispatch-retry.ts · delivery.ts · event-summaries.ts · reporter.ts · run-result.ts
    launch.ts · executor.ts · catalog.ts · discovery.ts · model-resolution.ts · types.ts · errors.ts
    tools/            dispatch · ask · cancel · list · wait · peer-messages · support   ← daemon/tool/
    surfaces.ts       registerAgentSurfaces — the isDaemonSpawnedAgent / isTopLevel tool wiring
                                                                                ← agent half of daemon/index.ts
    widget.ts         active-agents widget                                      ← daemon/widget.ts
    view/             summary · workstream  (HTTP observability parsers)         ← daemon/view/
    review/           /code-review (unchanged)
  workstreams/        launch_workstream · list · status  (unchanged; consumes #core/hub)
  skills/agents/
```

`swarm/agents/daemon/` dissolves: the adapter half goes to `#core/hub`, the agent half stays under `agents/`. Nothing in `pi/swarm/` defines a frame type or opens a socket — it calls `#core/hub`.

### 4.3 `pi/companion/` — a second consumer, via core

`thread-reporter.ts` imports `reportThread` + `ThreadReport` from `#core/hub/index.ts`. The `#swarm` re-export is deleted. Companion's policy (gate to top-level, build nodes from `getBranch()` at `agent_end`) is unchanged; only the import moves. This dissolves the `companion→swarm` edge.

### 4.4 The register split

`registerDaemonClient` already contains the seam. It splits along its existing branches:

- **core (`registerHubConnection`, called by `registerCore`):** derive identity → ensure + connect (top-level) or connect (spawned agent) → track connection, publish status, teardown at shutdown. Owns `awaitDaemonConnection`/`getActiveDaemonConnection` and the `processScoped("basecamp.daemonClient", …)` surviving state (key string unchanged — it is location-independent).
- **swarm (`registerAgentSurfaces`, called by `swarm/index.ts`):** if top-level and under depth cap, register dispatch/list/wait tools + the active-agents widget; if a daemon-spawned agent, register ask/peer/cancel tools + the run reporter + the peer-delivery handler. All obtain the connection via `#core/hub`'s `awaitDaemonConnection`.

Ordering is naturally correct: `extension.ts` registers core first, so the connection is established (and `awaitDaemonConnection` is resolvable) before any plugin needs it. Tools resolve the connection lazily at call time regardless.

## 5. The protocol home — frames move to core (decided)

The codec must decode **every** frame, so the `Frame` union and `encodeFrame`/`decodeFrame` cannot live in a plugin without core importing that plugin (violating "core imports no domain"). Decision (confirmed with the user): **all frame type definitions + the codec live in `core/hub/protocol/`, grouped by concern (`base` = handshake, `agents` = dispatch/wait/peer/…, `broker` = thread_report).** Plugins own the *logic that builds and consumes* frames; they do not own wire shapes.

This mirrors Python exactly — `hub/frames/swarm.py` is part of the `hub` package, not a separate `swarm` distribution — and it makes the frame defs *core's own code*, so the boundary invariant holds cleanly. "Swarm is just a plugin" is preserved in the sense that matters: swarm contributes behavior, and the wire protocol belongs to the hub (server = Python `hub`, client = `core/hub`).

Note the current TS/Python asymmetry the move also tidies: on Python, `TelemetryFrame`/`ResultReportFrame` sit in `frames/swarm.py` (agent-run reporting = a swarm concern); on TS they'll live in `protocol/agents.ts` as *types*, while the *reporting logic* (`reporter.ts`) stays in the swarm plugin. Types-by-concern in core; logic in the plugin.

## 6. Decisions & rejected alternatives

| Decision | Chosen | Rejected |
|---|---|---|
| Connector home | **`pi/core/hub/`** — core's hub-daemon adapter, peer to `core/git`/`core/host` | *Keep in swarm, hoist within* (§6.2's `pi/swarm/daemon/`): leaves a session-universal dependency inside a feature and keeps `companion→swarm`. |
| Frame-type home | **`core/hub/protocol/`** (all defs + codec, by concern) | *Frames stay in swarm*: forces `core→swarm` for the codec. *Extensible runtime-registered codec*: plugins register frame types at load — more machinery for no gain here. |
| Scope | **Ownership/relocation only**; SSOT deferred | *Fold in codegen now*: larger, riskier; the ownership move is the prerequisite, so sequence it first. |
| `swarm` status | **Remains a domain/plugin** consuming `#core/hub` | *Fold swarm into core too*: swarm is genuine feature breadth (tools, ACL-shaped collaboration, review, workstreams), not framework plumbing — it belongs outside core. |
| On-disk path | **Unchanged** (`~/.pi/basecamp/swarm/`) | *Rename to `…/hub/`*: separate, migration-bearing change; out of scope. |

## 7. Boundary & invariant impact

- **`core` still imports no other domain.** The moved code imports only `#core/*` (host/exec/env, ui, session, model, agent-mode/role) — already true today — plus its own new `core/hub/*`. Frame defs become core-owned.
- **`#core/*` is public API (~145 sites), but this is additive.** We are *adding* `core/hub/*`, not restructuring existing core paths, so no existing `#core/...` specifier changes. New import sites (`#core/hub/index.ts`, `#core/hub/protocol/index.ts`) appear in swarm + companion.
- **`#swarm` shrinks.** The `reportThread` re-export from `pi/swarm/index.ts` is deleted; `#swarm` no longer exports any transport. Boundary-check `CONTEXTS` count is unchanged (swarm + companion remain domains); the `companion→swarm` **edge** disappears.
- **Surviving state key is stable.** `processScoped("basecamp.daemonClient", …)` is keyed by string, not module path, so moving the file preserves `/reload` survival. Same for the reload-survival of the live WebSocket.
- **`biome.json` + linter-blind paths.** The `swarm/protocol` biome exclude re-anchors to `core/hub/protocol`. `daemon-frames.test.ts` reads the Python `frames.py` by hardcoded path to assert `PROTOCOL_VERSION` parity — it re-points to `core/hub/protocol/` and to `src/basecamp/hub/frames/`. Both are linter-blind → hand-fix + green `make test` (§8).

## 8. Migration sequencing (green at every step)

Relocation-first, mechanical moves with `git mv`, each a `make lint` + `make test`-green commit:

1. **Protocol to core.** Create `pi/core/hub/protocol/`; move `agents/daemon/frames/*` (codec + types, regrouped `base`/`agents`/`broker`) and `pi/swarm/protocol/` (fixtures + PROTOCOL.md) into it. Repoint every in-swarm frame import to `#core/hub/protocol`. Fix the two linter-blind paths (`daemon-frames.test.ts`, biome exclude). Green.
2. **Transport + ensure + identity + status to core.** Move `connection.ts`, `paths.ts`, `handles.ts`, `http.ts`, `status.ts`, `spawn.ts`+`process.ts`→`ensure.ts`; tease `deriveDaemonIdentity` out of `daemon/index.ts` into `core/hub/identity.ts`; add `core/hub/index.ts` (`registerHubConnection` + accessors) and register it from `registerCore`. Swarm temporarily imports these from `#core/hub`. Green.
3. **Report-thread to core; repoint companion.** Move `report-thread.ts` to `core/hub/`; change `pi/companion/thread-reporter.ts` to import from `#core/hub`; delete the `#swarm` `reportThread` re-export. Green — `companion→swarm` edge gone.
4. **Collapse the swarm agent half.** Rename `rpc.ts`→`agents/client.ts` (agent request methods only, on `#core/hub`); move `tool/`→`agents/tools/`, `widget.ts`, `view/`, `reporter.ts`, `delivery.ts`, `dispatch-retry.ts`, `event-summaries.ts`, `run-result.ts` up under `agents/`; split the agent-registration branch of the old `daemon/index.ts` into `agents/surfaces.ts`. `agents/daemon/` is now empty and removed. Green.
5. **Doc truing** (§11).

Each step is independently revertable; steps 1–3 already deliver the headline win (frames + connector + companion edge), with step 4 the internal tidy.

## 9. Risks

- **Core is the hottest boundary.** Mitigated by additivity (§7): no existing `#core/*` path changes; we only add `core/hub/*`.
- **Connection lifecycle regressions** (connect/reconnect/teardown, the `connecting`-promise generation guard, spawned-agent reporter wiring). Mitigated by moving the lifecycle wholesale (not rewriting it) and by the existing daemon-client + reporter test suites; the split is along the function's existing branches.
- **Two linter-blind path reads** (step 1) — caught by `make test`, not the boundary checker; hand-fixed and asserted green.
- **`core/hub` is near the same cap pressure** the connector already had (`daemon/index.ts` was 337/350). Splitting identity/ensure/lifecycle into separate core files (as specced) resolves it rather than inherits it.

## 10. Deferred — future moves (documented, not this pass)

- **Protocol single-source-of-truth / codegen.** With all frame shapes in `core/hub/protocol/`, generate the TS `Frame` union + `FRAME_TYPES` and (ideally) the Python Pydantic models and the HTTP-response + run-result-sidecar types from one source (extend the `protocol/frames/*.json`). This kills the ~15-edit-site, cross-language, per-version tax the swarm audit ranked #1 and [async-agents.md](./async-agents.md) §8 flagged as the top risk. The ownership move here is its prerequisite.
- **Consolidate the third daemon client.** `src/basecamp/companion/daemon/` (691 LOC) re-parses hub HTTP payloads into parallel dataclasses; fold onto shared models once SSOT lands ([repo-rearchitecture.md](./repo-rearchitecture.md) §6.4 follow-up).
- **Python-daemon-internal simplification.** Extract `runner.py`'s `AttemptDaemonProxy`; replace `app.py`'s isinstance router with dict-dispatch; flatten `store/` trivial trios and factor the column-migration idiom. (Swarm audit findings ③④⑤.)
- **Companion feature-cleanups.** Split `diff.py` (479/500); trim the write-only snapshot fields; rename `DaemonSummarySource`→`DaemonClient` and `registerCompanion`→`registerSnapshot`; fix the stale `cycles.py` doc path. (Companion audit.)
- **On-disk `~/.pi/basecamp/swarm/` → `…/hub/`** rename (migration-bearing).

## 11. Doc truing (at execution)

- **AGENTS.md** — Repo Map: `core/` gains `hub/` (the connector); `swarm/` description drops "daemon client/reporting code," becomes the agent plugin over `#core/hub`; the Environment/architecture notes and the `protocol v19`→`v20` lag.
- **`pi/core/README.md`** — add the `hub/` adapter beside `git`/`host`/`model`.
- **`pi/swarm/README.md`** — reframe as the plugin; drop transport ownership; point the protocol at `#core/hub/protocol`.
- **`pi/companion/README.md`** — dependency list: `#swarm` → `#core/hub`.
- **`pi/core/hub/protocol/PROTOCOL.md`** — moved from `pi/swarm/protocol/`; note the new home.
- **This doc + [async-agents.md](./async-agents.md) / [companion-daemon-broker.md](./companion-daemon-broker.md)** — cross-links; fix the stale `frames/index.ts` comment path.

## 12. Execution status

Shipped as green (`make lint` + full TS suite) commits on `claude/arch-simplify-companion-swarm-0sz5f0`:

1. **Protocol → core** (`b00e761`). The TS codec + frame types, the JSON fixtures, and `PROTOCOL.md` moved to `pi/core/hub/protocol/`; every importer + the two linter-blind contract tests (TS + Python) + the biome exclude re-anchored. *Deviation from §8.1:* the per-family frame files (`dispatch.ts`, `wait.ts`, …) were relocated **as-is**, not consolidated into `base`/`agents`/`broker` — a cosmetic within-core regroup left as a follow-up so the move stayed pure relocation.
2. **Connector → core** (`f4338d3`). `connection`/`spawn`/`process`/`paths`/`handles`/`http`/`status` → `pi/core/hub/`; `deriveDaemonIdentity` + `sanitizeDisplayLabel` → `identity.ts`; `registerDaemonClient` split into `registerHubConnection` (core, with the `onDaemonConnect` seam) and `registerAgentSurfaces` (swarm); the reporter takes `awaitConnection()`. *Deviation from §4.1:* `spawn.ts` + `process.ts` were **not** merged into `ensure.ts` (the merge would have breached the 350-line cap) — kept as separate core files.
3. **Report-thread → core; companion repointed** (`935d799`). `reportThread` → `pi/core/hub/report-thread.ts` (companion imports it deep, avoiding an `index`↔`report-thread` cycle); the `#swarm` re-export deleted; `companion→swarm` edge gone (companion imports only `#core/*` + `#tasks`).
4. **Doc-truing** (`f62d9e9`) — §11 (AGENTS.md, the four READMEs, this record).
5. **Swarm flatten** (this commit) — §8.4. `pi/swarm/agents/daemon/` dissolved into `pi/swarm/agents/`: the agent-side files (`client`/`rpc`/`tools`/`reporter`/`delivery`/`dispatch-retry`/`event-summaries`/`run-result`/`widget`, plus `tool/` and `view/`) moved up; `daemon/index.ts` → `surfaces.ts` (`registerAgentSurfaces`). *Deviation from §8.4:* the `client.ts` barrel was **kept** (not dissolved) — it re-exports the connection types from `#core/hub`, the request client from `rpc.ts`, and the observability views from `view/`, so external consumers (workstreams, review, tests) needed only path swaps rather than semantic splitting; `rpc.ts` keeps its name behind it. `agents/` is now the honest home of the plugin. Pure internal reorganization — no cross-domain, behavior, or wire change.

The repivot is complete. Optional later polish (not blocking): consolidate the per-family frame files into `base`/`agents`/`broker` (§8.1 deviation); merge `agents/tools.ts` + `agents/tool/` into one `tools/` dir; drop the `daemon-` prefix on the relocated `agents/tests/` files. And the standing follow-ups in §10 (protocol SSOT/codegen, the third companion daemon client, the Python `runner.py`/`app.py` internals).
