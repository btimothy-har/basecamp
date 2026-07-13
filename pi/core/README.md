# core

The always-present foundation domain for basecamp. `pi/core` is the first module the composition root (`pi/extension.ts`) registers; every other domain may import it freely (`#core/*`). `src/basecamp/core` is the Python side (`basecamp.core`: settings, paths, files, exceptions, plus the project-config schema, migrations, directories, and its management CLI).

## What it does

- **Host primitives** (`host/`): the boundary to the runtime we're hosted in — process exec + cwd provider (`host/exec.ts`), config-file IO (`host/config.ts`), and paths (`host/paths.ts`)
- **Environment contract** (`host/env.ts`): typed `BASECAMP_*` env var getters/setters, companion-active flag, workspace state hooks for the workspace module's override
- **Hub connector** (`hub/`): core's adapter for the hub daemon — the WebSocket transport + register/handshake, ensure-daemon (spawn/health/version), node-identity derivation, the connection-status footer, and the **raw-thread reporter** (`thread-reporter.ts` — ships `getBranch()` at `agent_end`) with its `reportThread` transport, plus the shared **wire protocol** (`hub/protocol/`: the TS codec + frame types, the JSON fixtures, and `PROTOCOL.md`, kept in lockstep with the Python `basecamp.hub`). `registerCore` opens the connection at `session_start` for top-level sessions and daemon-spawned agents **and registers the reporter** — "connect + report" is one core responsibility — exposing `awaitDaemonConnection`/`onDaemonConnect`. The agent-dispatch primitive (`swarm/`, a sibling core adapter) consumes the connection; `companion` no longer produces analysis data — the daemon derives it from the reported thread and companion is a downstream consumer.
- **Agent-dispatch primitive** (`swarm/`): core's adapter for the async-agent runtime, a peer of `hub/` — the builtin agent catalog, the dispatch/ask/cancel/wait/peer tools, the launch-spec builder, the run reporter, and the active-agents widget, all over `#core/hub`. `registerCore` registers it right after the hub connector (`registerSwarm`, for top-level sessions and daemon-spawned agents alike). It is **substrate, not a feature** — multiple domains dispatch agents — so the `#code-review` and `#workstreams` feature domains build on it via `#core/swarm/agents/*`. The Python server side is `basecamp.hub.swarm`; the on-disk runtime path stays `~/.pi/basecamp/swarm/`.
- **Ports** (seams core declares, other domains implement — each co-located with its concept, not bucketed): the tool/skill catalog (`catalog/`), model-alias resolution (`model/`), and the workspace service (`workspace/service.ts`)
- **Reload-survival** (`global-registry.ts`): `processScoped` — the one place live state is pinned across `/reload`
- **Session lifecycle**: agent-mode state machine (analysis/planning/work/copilot), session start (state load + mode restore), session shutdown, chat compaction
- **State persistence**: file-backed session state (`~/.pi/basecamp/core/session-state/<session-id>.json`) with fork inheritance
- **Skills** (`skills/`): the `skill()` tool, SKILL.md content parsing, and the invocation tracker (store + lifecycle in `tracker.ts`); the tool/skill catalog registry is its sibling `catalog/`
- **Model** (`model/`): the alias provider seam + native config provider (reads the `model_aliases` section of `~/.pi/basecamp/config.json`; writes shell out to `basecamp config alias`) + the `/model-aliases` command, plus `model/resolution.ts` (string→Model, reasoning-effort, tool-choice)
- **Escalate**: the `escalate` tool — pause and ask the user for a decision (primary sessions only)
- **Framework UI** (`ui/`): the session's status footer, title auto-naming, and interactive mode editor — framework chrome, registered last by `registerCore`. Feature-specific widgets live with their own domains; only `formatTitle` is consumed externally (via `#core/ui/index.ts`).
- **Project config** (`project/`): resolve repo → project → `BASECAMP_PROJECT`, the project-config schema, and nested-doc context injection. Core-owned but registered by the workspace module (its session_start hook needs workspace runtime state); prompt assembly lives in the workspace domain.
- **Workspace defaults**: git detection at session_start (repo, remote, branch from `process.cwd()`); worktree operations (list/activate/attach) as thin git wrappers. The workspace module overrides these defaults with basecamp-config-aware values during registration.

## Architecture

Core is the foundation of the boundary rules (`scripts/check-boundaries.ts`): every context may import `#core/*`; core imports no other context. Cross-context observation of feature state (e.g. companion → tasks) goes through the owning context's public index (`#tasks/index.ts`), never through core bridges.

### State convention: wiring vs. surviving

There are two kinds of module state, with different rules:

- **Wiring** — providers and registries that the composition root re-establishes on every load (including `/reload`): cwd provider, catalog providers, model-alias providers, workspace service registration, copilot-launch reader, workspace hooks. These are **plain module state** (`let`/`const` at module scope). Re-registration on reload is guaranteed because `extension.ts` runs every module's `register*` in a fixed order; converting these to module state also stops stale pre-reload listener closures from firing.

- **Surviving state** — live session data that must outlive `/reload` (pi re-imports the extension with fresh module instances, `moduleCache: false`): session state, agent mode, invoked skills, the workspace runtime service, project runtime, companion pane/analysis state, the daemon WebSocket client. These use `processScoped(key, init)` from [`global-registry.ts`](global-registry.ts), which stores the value on `globalThis` behind a `Symbol.for` key. Key strings are stable across releases — renaming one silently drops state at the next `/reload`.

When adding state, default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session.

### Init ordering

`extension.ts` registers modules in a fixed order with core first, so core's `session_start` handlers run before any other module's. Later modules may assume core-owned state (session state, agent mode) is initialized for every lifecycle event.
