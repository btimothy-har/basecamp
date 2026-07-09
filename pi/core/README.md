# core

The always-present foundation domain for basecamp. `pi/core` is the first module the composition root (`pi/extension.ts`) registers; every other domain may import it freely (`#core/*`). `src/basecamp/core` is the Python side (`basecamp.core`: settings, paths, files, exceptions, plus the project-config schema, migrations, directories, and its management CLI).

## What it does

- **Platform registries**: exec/cwd provider, capability catalog, model-alias resolve hooks, workspace service seam, product-role and agent-identity providers
- **Environment contract** (`platform/env.ts`): typed `BASECAMP_*` env var getters/setters, companion-active flag, workspace state hooks for the workspace module's override
- **Session lifecycle**: agent-mode state machine (analysis/planning/supervisor/executor/copilot), session start (state load + mode restore), session shutdown, chat compaction
- **State persistence**: file-backed session state (`~/.pi/basecamp/core/session-state/<session-id>.json`) with fork inheritance
- **Capabilities**: the `skill()` tool, SKILL.md content parsing, catalog providers, skill invocation tracker
- **Model aliases**: native config provider (`~/.pi/basecamp/core/model-aliases.json`) + the `/model-aliases` command
- **Escalate**: the `escalate` tool — pause and ask the user for a decision (primary sessions only)
- **Project config** (`project/`): resolve repo → project → `BASECAMP_PROJECT`, the project-config schema, and nested-doc context injection. Core-owned but registered by the workspace module (its session_start hook needs workspace runtime state); prompt assembly lives in the workspace domain.
- **Workspace defaults**: git detection at session_start (repo, remote, branch from `process.cwd()`); worktree operations (list/activate/attach) as thin git wrappers. The workspace module overrides these defaults with basecamp-config-aware values during registration.

## Architecture

Core is the foundation of the boundary rules (`scripts/check-boundaries.ts`): every context may import `#core/*`; core imports no other context. Cross-context observation of feature state (e.g. companion → tasks) goes through the owning context's public index (`#tasks/index.ts`), never through core bridges.

### State convention: wiring vs. surviving

There are two kinds of module state, with different rules:

- **Wiring** — providers and registries that the composition root re-establishes on every load (including `/reload`): cwd provider, catalog providers, model-alias providers, workspace service registration, copilot-launch reader, product-role/agent-identity providers, workspace hooks. These are **plain module state** (`let`/`const` at module scope). Re-registration on reload is guaranteed because `extension.ts` runs every module's `register*` in a fixed order; converting these to module state also stops stale pre-reload listener closures from firing.

- **Surviving state** — live session data that must outlive `/reload` (pi re-imports the extension with fresh module instances, `moduleCache: false`): session state, agent mode, invoked skills, the workspace runtime service, project runtime, companion pane/analysis state, the daemon WebSocket client. These use `processScoped(key, init)` from [`platform/global-registry.ts`](platform/global-registry.ts), which stores the value on `globalThis` behind a `Symbol.for` key. Key strings are stable across releases — renaming one silently drops state at the next `/reload`.

When adding state, default to plain module state; reach for `processScoped` only when losing the value on `/reload` would break the live session.

### Init ordering

`extension.ts` registers modules in a fixed order with core first, so core's `session_start` handlers run before any other module's. Later modules may assume core-owned state (session state, agent mode) is initialized for every lifecycle event.
