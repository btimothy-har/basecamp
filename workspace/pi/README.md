# pi-workspace

Basecamp workspace config + project context layer. Overrides pi-core's git-detected workspace defaults with basecamp.yaml-aware values.

## What it does

- **Workspace config**: loads `basecamp.yaml`, manages allowed-roots providers, unsafe-edit flag handling
- **Projects**: assembles the layered system prompt (environment → working style → project context → tools/skills), context injection on every prompt cycle, header rendering
- **WorkspaceService override**: registers a config-aware WorkspaceService into pi-core's workspace registry, replacing pi-core's default. Sets `BASECAMP_*` env vars via pi-core's env contract. Registers cwd provider via pi-core's exec seam.
- **Workspace guards**: blocks writes to critical root-branch paths, warns of unsaved session states
- **Worktree command**: `/worktree` command for switching between git worktrees (primary sessions only)

## Repo copilot Logseq memory

Copilot mode can use a configured Logseq graph as durable repo memory. Configure the graph manually in `~/.pi/basecamp/config.json`:

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

Logseq is the durable memory; workstreams are the user-facing execution surfaces. When copilot stages a workstream (via `launch_workstream` in pi-tasks) it provisions a worktree + Herdr pane and returns a human-typeable id; the user runs `pi` in that pane and `/workstream <id>` to start the session, which stamps its handle onto the launch record. The launch index records only an operational receipt — not workstream status. Copilot refreshes a workstream's state on demand by finding it with `list_workstream_launches` and pulling a summary from its stored handle via pi-swarm `ask_agent`/`message_agent`, then curates the durable parts into Logseq itself. Workstream agents never write Logseq and do not push updates to copilot.

## Dependencies

- **pi-core** (hard peer dep): workspace registry, exec, env contract, state persistence, worktree git primitives

## Installation

```bash
pi install /path/to/workspace/pi
```

Installed automatically by `install.py`.
