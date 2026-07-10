# workspace (core subsystem)

The workspace runtime — everything about *where the agent works and what it may edit*. A `pi/core/workspace/` subsystem registered by `registerCore` (via `registerWorkspace`), not a standalone domain. `basecamp.workspace` (`src/basecamp/workspace/`) is the Python side: per-repo worktree-setup environments + interactive CLI menus.

## What it does

- **Runtime** (`runtime.ts`) — `WorkspaceRuntimeService`: the active-worktree state machine, effective-cwd resolution, `BASECAMP_*` env vars, and the cwd provider. Survives `/reload` (process-scoped).
- **Session bootstrap** (`session.ts`) — `session_start`: init, legacy-worktree migration, worktree restore on resume/reload, `.env` load, the `--worktree-dir` / `--read-only` / `--unsafe-edit` flags, and the Logseq allowed-root.
- **Edit guards** (`guards.ts` + `unsafe-edit.ts`) — `tool_call`/`user_bash`: block writes to the protected checkout, retarget relative file-tool paths + `!bash` into the active worktree.
- **Command** (`command.ts`) — `/worktree` to switch worktrees (primary sessions only).
- **State + accessors** (`service.ts`) — the shared `WorkspaceState` / `WorkspaceWorktree` types, the state accessors (`getWorkspaceState`, `requireWorkspaceState`, `getWorkspaceEffectiveCwd`, `onWorkspaceChange`, `activate`/`attachWorkspaceWorktree`, …), and the allowed-roots registry. The accessors are thin reads over the runtime — there is no pluggable `WorkspaceService` seam.
- **Git primitives** — `worktree.ts` · `repo.ts` · `migrate.ts` · `affinity.ts` · `worktree-target.ts` · `setup.ts` · `constants.ts`: stateless git-worktree mechanics, also imported directly by swarm (workstream provisioning).

`registerWorkspace` wires runtime → session → guards → command; `registerCore` calls it just before `registerProject` (project's `session_start` reads workspace state). State is read across the extension through `#core/workspace/service.ts`.

> System-prompt assembly (environment → working style → project context → capabilities) lives in the **`system-prompt`** domain; project resolution + context injection are `#core/project`; the banner is `#core/ui`.

## Repo copilot Logseq memory

Copilot is a locked, launch-only mode entered with `pi --copilot`: it is immutable (shift+tab can neither enter nor leave it) and the `plan()` handoff is disabled in it. Copilot mode can use a configured Logseq graph as durable repo memory. Configure the graph manually in `~/.pi/basecamp/config.json`:

```json
{
	"logseq": {
		"graph_dir": "~/logseq/main"
	}
}
```

The path must exist and point at the Logseq graph root. Basecamp expects normal Logseq page files under the graph's `pages/` directory.

Repo memory uses safe page names that match filenames directly:

- Repo cockpit: `pages/repo__<org>__<repo>.md`
- Work dossier: `pages/work__<org>__<repo>__<slug>.md`

For example, `btimothy-har/basecamp` uses:

- `pages/repo__btimothy-har__basecamp.md`
- `pages/work__btimothy-har__basecamp__gh-220.md`

The repo cockpit captures repo-level coordination state: current user focus, priority shifts, active/paused/waiting/not-now work, and cross-workstream decisions. Work dossiers hold durable context and status for one work item.

Basecamp registers the configured graph as an allowed root so normal file tools can read and update these Markdown files from repo sessions. There are no custom Logseq tools, no background sync, and no automatic graph scan.

Logseq is the durable memory; workstreams are the user-facing execution surfaces. When copilot stages a workstream (via `launch_workstream`, owned by the swarm context) it provisions a generically-named worktree (`copilot/<slug>`) + Herdr pane and creates the workstream in the daemon, returning its internal `ws_<uuid>` id and three-word `slug`; the user runs `pi --workstream` in that pane to start the session (bare form infers the slug from the worktree), which attaches the session as a workstream agent in the daemon. If no pane opens, the user can run `cd <worktree-path> && pi --workstream=<slug>` manually. The workstream is durable internal coordination state in the daemon (not an operational receipt); the dossier remains the durable record of priority, decisions, blockers, and done signals. Copilot refreshes a workstream's state on demand by finding it with `list_workstreams` (a single-identifier lookup returns the joined agent rows) and pulling a summary from the relevant session's attached handle via the swarm `ask_agent`/`message_agent` tools — a workstream may have several attached sessions, so copilot picks the one it needs — then curates the durable parts into Logseq itself. A workstream can have several agent sessions over time or concurrently. Workstream agents never write Logseq and do not push updates to copilot.

## Dependencies

- Everything here imports only sibling `#core/*` modules (host exec/env/config, session state, global-registry). The git primitives are the low-level worktree mechanics the rest of the subsystem — and swarm — build on.
