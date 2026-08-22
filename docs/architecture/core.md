# Core Substrate

`pi/core` is the foundation domain: the always-present substrate every other domain builds on. The composition root (`pi/extension.ts`) registers it first, so its state is ready before any feature domain loads. Every domain may import `#core/*` freely; **core imports no other domain.** The Python side is `basecamp.core` (settings, paths, files, exceptions, the project-config schema and migrations, and the management CLI).

## Layering

```
  Feature domains
  code-review · workstreams · pull-request
              │
              │  import #core/*  (one-way)
              ▼
 ┌─────────────────────────────────────┐
 │        Core substrate (pi/core)     │
 │                                     │
 │  swarm ──▶ hub      host · env      │
 │  (dispatch           skills · model │
 │   primitive)         UI · project   │
 │                      workspace     │
 └─────────────────────────────────────┘
              │
              │  WebSocket over UDS
              ▼
  basecamp.hub (daemon)  ·  basecamp.core
```

Feature domains import `#core/*`; core imports nothing back. The dependency arrow points one way.

Two things in core are **primitives, not features**: the hub connector and the agent-dispatch primitive. Several feature domains build on them, which is why they live in core rather than in any one domain that consumes them. A capability with a single consumer belongs in that consumer's domain; core is for substrate.

## Subsystems

### The hub connector

`hub/` is core's adapter for the hub daemon: WebSocket transport, register/handshake, ensure-daemon (spawn, health, version), node identity, and the connection-status footer. It owns the shared wire protocol (`hub/protocol/`, kept in lockstep with Python `basecamp.hub`). `registerCore` opens the connection at `session_start` for top-level sessions and daemon-spawned agents, and exposes `awaitDaemonConnection` / `onDaemonConnect` to the features that need it.

### The agent-dispatch primitive

`swarm/` is core's adapter for the async-agent runtime, riding on `#core/hub`. It owns the builtin agent catalog, the dispatch/ask/cancel/wait/peer tools, the launch-spec builder, the run reporter, and the active-agents widget. `#code-review` and `#workstreams` both dispatch agents, so they consume it via `#core/swarm/agents/*` rather than each owning a copy. The Python server side is `basecamp.hub.swarm`.

### Host boundary

`host/` is how core touches the runtime it is hosted in: process exec and the cwd provider, config-file IO, paths, and the typed `BASECAMP_*` env contract with agent-depth helpers.

### Session lifecycle and state

The agent-mode state machine (`analysis` / `planning` / `work` / `copilot`), session start (state load + mode restore), shutdown, and chat compaction. Session state is file-backed (`~/.pi/basecamp/core/session-state/`) with fork inheritance, and live state survives `/reload` via `processScoped` from `global-registry.ts`.

### Tools and registries

The capabilities core ships to every session:

- **Skills** (`skills/` + `catalog/`): the `skill()` tool, `SKILL.md` parsing, the invocation tracker, and the tool/skill catalog registry.
- **Model** (`model/`): the alias provider seam, the native config provider (reads `model_aliases` from `~/.pi/basecamp/config.json`; writes shell out to `basecamp config alias`), the `/model-aliases` command, and model-string resolution.
- **Escalate**: pauses the session to ask the user for a decision (primary sessions only).

Core also declares the seams other domains implement (its ports): the tool/skill catalog, model-alias resolution, and the workspace service.

### Project and workspace

- **Project config** (`project/`): resolves repo → project → `BASECAMP_PROJECT`, owns the project-config schema and nested-doc context injection. Core-owned but registered by the workspace module, whose `session_start` hook it needs; prompt assembly lives in the workspace domain.
- **Workspace defaults**: git detection at `session_start` and worktree operations (list/activate/attach) as thin git wrappers, overridden with config-aware values by the workspace module during registration.

### Framework UI

`ui/` is the session's chrome: the status footer, title auto-naming, and the interactive mode editor. Feature-specific widgets live with their own domains.
