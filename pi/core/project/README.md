# project

The active project's working environment — *which project the session is in, its context, and where the agent works*. A `pi/core/project/` subsystem registered by `registerCore` (via `registerProject`). `basecamp.workspace` (`src/basecamp/workspace/`) is the Python side: per-repo worktree-setup environments + interactive CLI menus.

## What it does

- **`config.ts`** — resolve the project from the `projects` section of `~/.pi/basecamp/config.json` (by repo root → name, `additionalDirs`, `workingStyle`, context; context overrides live in `~/.pi/basecamp/context/`), hold the `ProjectState` cell, and register the `session_start` resolve + `BASECAMP_PROJECT`.
- **`context.ts`** — discover ancestor `AGENTS.md`/`CLAUDE.md` context files.
- **`injection.ts`** — a `tool_result` hook that injects nested `AGENTS.md`/`CLAUDE.md` just-in-time as the agent enters a subtree that has its own.
- **`logseq.ts`** — the copilot repo-memory (Logseq) context block.
- **`workspace/`** — the active working environment (below).

### `workspace/` — the worktree runtime

- **`runtime.ts`** — `WorkspaceRuntimeService`: active-worktree state machine, effective cwd, `BASECAMP_*` env, cwd provider (survives `/reload`).
- **`state.ts`** — `WorkspaceState` types + accessors (`getWorkspaceState`, `getWorkspaceEffectiveCwd`, `onWorkspaceChange`, `activate`/`attachWorkspaceWorktree`, …) + the allowed-roots registry. Thin reads over the runtime — no pluggable seam.
- **`session.ts`** — `session_start` bootstrap: init, legacy-worktree migration, restore, `.env`, the `--worktree-dir`/`--read-only`/`--unsafe-edit` flags, the Logseq allowed-root.
- **`guards.ts` · `unsafe-edit.ts`** — edit guards: block writes to the protected checkout, retarget paths into the active worktree.
- **`command.ts`** (`/worktree`, primary only) · **`affinity.ts`** (session↔worktree bridge) · **`setup.ts`** (per-repo worktree-setup command).

## Registration & ordering

`registerProject` sequences **workspace bootstrap → project resolve → context injection** in one function, so project's `session_start` (which reads workspace state) runs after workspace init without a cross-module trick. The allowed-roots registry is internal — `config.ts` registers `projects`, `workspace/session.ts` registers `logseq`.

## Dependencies

- **`#core/git/*`** — the worktree runtime consumes the git mechanics. Otherwise `#core/*` only (host, session state, global-registry). Read across the extension via `#core/project/workspace/state.ts` (workspace) and `#core/project/config.ts` (project state).

## Repo copilot Logseq memory

Copilot is a locked, launch-only mode entered with `pi --copilot`: it is immutable (shift+tab can neither enter nor leave it) and the `plan()` handoff is disabled in it. Copilot mode can use a configured Logseq graph as durable repo memory. Configure the graph manually in `~/.pi/basecamp/config.json`:

```json
{
	"logseq": {
		"graph_dir": "~/logseq/main"
	}
}
```

The path must exist and point at the Logseq graph root. Basecamp expects normal Logseq page files under the graph's `pages/` directory. Repo memory uses safe page names that match filenames directly:

- Repo cockpit: `pages/repo__<org>__<repo>.md` — repo-level coordination state (current focus, priority shifts, active/paused/waiting work, cross-workstream decisions).
- Work dossier: `pages/work__<org>__<repo>__<slug>.md` — durable context + status for one work item.

Basecamp registers the configured graph as an allowed root (via `workspace/session.ts`) so normal file tools can read/update these Markdown files from repo sessions. There are no custom Logseq tools, no background sync, and no automatic graph scan.

Logseq is the durable memory; workstreams are the user-facing execution surfaces. When copilot stages a workstream (via `launch_workstream`, owned by the swarm context) it provisions a `copilot/<slug>` worktree + Herdr pane and creates the workstream in the daemon; the user runs `pi --workstream` in that pane (bare form infers the slug from the worktree). The dossier remains the durable record of priority, decisions, blockers, and done signals. Workstream agents never write Logseq and do not push updates to copilot.
