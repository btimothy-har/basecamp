# Core Substrate

`pi/core` is the foundation domain, the always-present substrate every other domain builds on. The composition root (`pi/extension.ts`) registers it first, so its state is ready before any feature domain loads. Every domain may import `#core/*` freely; **core imports no other domain.** The dependency arrow points one way.

The Python side is `src/basecamp/core` (`basecamp.core`): settings, paths, files, exceptions, the project-config schema and its migrations, and the management CLI.

## Layering

```
   Feature domains
   code-review · workstreams · pull-request
              │
              │  import #core/*   (one-way: down only; core imports nothing)
              ▼
 ════════════════════════════════════════════════════
   Core substrate    (pi/core, registered first)
 ════════════════════════════════════════════════════

     swarm ──▶ hub              host · env
     (agent-dispatch            session lifecycle · state
      primitive)                skills · model · UI
                                ports · project · workspace

              │
              │  WebSocket over UDS
              ▼
   basecamp.hub    (daemon + swarm server)
   basecamp.core   (settings · paths · config schema · CLI)
```

Two things in core are **primitives, not features**: the hub connector and the agent-dispatch primitive. They are peers of each other, and several feature domains build on them, which is why they live in core rather than in a domain that consumes them.

### The hub connector (`hub/`)

Core's adapter for the hub daemon: the WebSocket transport, register/handshake, ensure-daemon (spawn, health, version), node-identity derivation, and the connection-status footer. It owns the shared wire protocol (`hub/protocol/`: the TypeScript codec, frame types, JSON fixtures, and `PROTOCOL.md`, kept in lockstep with Python `basecamp.hub`). `registerCore` opens the connection at `session_start` for top-level sessions and daemon-spawned agents, and exposes `awaitDaemonConnection` / `onDaemonConnect` to the features that need it.

### The agent-dispatch primitive (`swarm/`)

Core's adapter for the async-agent runtime, riding on `#core/hub`. It owns the builtin agent catalog, the dispatch/ask/cancel/wait/peer tools, the launch-spec builder, the run reporter, and the active-agents widget. `registerCore` registers it (`registerSwarm`) right after the hub connector, for top-level sessions and daemon-spawned agents alike. It is **substrate, not a feature**: `#code-review` and `#workstreams` both dispatch agents, so they consume it via `#core/swarm/agents/*` rather than each owning a copy. The Python server side is `basecamp.hub.swarm`; the on-disk runtime path is `~/.pi/basecamp/swarm/`.

## The rest of core

- **Host primitives** (`host/`): the boundary to the runtime we are hosted in. Process exec and the cwd provider (`host/exec.ts`), config-file IO (`host/config.ts`), and paths (`host/paths.ts`).
- **Environment contract** (`host/env.ts`): typed `BASECAMP_*` getters/setters and agent-depth helpers.
- **Session lifecycle**: the agent-mode state machine (`analysis` / `planning` / `work` / `copilot`), session start (state load + mode restore), shutdown, and chat compaction.
- **State persistence**: file-backed session state (`~/.pi/basecamp/core/session-state/<session-id>.json`) with fork inheritance.
- **Reload survival** (`global-registry.ts`): `processScoped`, the one place live state is pinned across `/reload` (see [State convention](#state-convention-wiring-vs-surviving)).
- **Skills** (`skills/`): the `skill()` tool, `SKILL.md` parsing, and the invocation tracker (`tracker.ts`). The tool/skill catalog registry is its sibling `catalog/`.
- **Model** (`model/`): the alias provider seam, the native config provider (reads the `model_aliases` section of `~/.pi/basecamp/config.json`; writes shell out to `basecamp config alias`), the `/model-aliases` command, and `model/resolution.ts` (string → Model, reasoning-effort, tool-choice).
- **Escalate**: the `escalate` tool pauses the session to ask the user for a decision (primary sessions only).
- **Framework UI** (`ui/`): the status footer, title auto-naming, and the interactive mode editor (the framework chrome, registered last by `registerCore`). Feature-specific widgets live with their own domains; only `formatTitle` is consumed externally, via `#core/ui/index.ts`.
- **Ports** (seams core declares and other domains implement, each co-located with its concept): the tool/skill catalog (`catalog/`), model-alias resolution (`model/`), and the workspace service (`workspace/service.ts`).
- **Project config** (`project/`): resolve repo → project → `BASECAMP_PROJECT`, the project-config schema, and nested-doc context injection. Core-owned but registered by the workspace module, because its `session_start` hook needs workspace runtime state; prompt assembly lives in the workspace domain.
- **Workspace defaults**: git detection at `session_start` (repo, remote, branch from `process.cwd()`) and worktree operations (list/activate/attach) as thin git wrappers. The workspace module overrides these with config-aware values during registration.

## Boundary rule

Core is the foundation of the repo-wide boundary rules (`scripts/check-boundaries.ts`): every context may import `#core/*`, and core imports no other context. Cross-context imports go through the owning context's public index, never deep internal paths.

The `#core/*` alias is free from **inside** core too. A file reaches anything outside its own directory by alias, not by climbing: `./sibling.ts` is the only legal relative form, and every `../` is spelled `#core/hub/protocol/index.ts`. This holds repo-wide. Each context reaches its own files as `#<context>/…`, so a specifier states *where the target lives* rather than *how far up to climb*, and survives either file moving. It is enforced, not advisory: a reintroduced `../` fails the boundary check with the alias to use.

## State convention: wiring vs. surviving

Two kinds of module state, two rules.

- **Wiring** is providers and registries the composition root re-establishes on every load, `/reload` included: the cwd provider, catalog providers, model-alias providers, workspace service registration, and workspace hooks. These are **plain module state** (`let` / `const` at module scope). Re-registration is guaranteed because `extension.ts` runs every module's `register*` in a fixed order, and keeping them as module state also stops stale pre-reload listener closures from firing.
- **Surviving state** is live session data that must outlive `/reload` (Pi re-imports the extension with fresh module instances, `moduleCache: false`): session state, agent mode, invoked skills, the workspace runtime service, project runtime, and the daemon WebSocket client. These use `processScoped(key, init)` from `global-registry.ts`, which stores the value on `globalThis` behind a `Symbol.for` key. Key strings are stable across releases; renaming one silently drops state at the next `/reload`.

Default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session.

## Init ordering

`extension.ts` registers modules in a fixed order with core first, so core's `session_start` handlers run before any other module's. Later modules may assume core-owned state (session state, agent mode) is initialized for every lifecycle event.
