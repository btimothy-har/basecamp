# basecamp

Project-aware **Claude Code plugin** for AI coding agents. Injects each project's
related directories and curated context into the session, ships engineering
skills and a copilot workflow, drives the session lifecycle through fail-open
hooks, and persists coordination state (sessions, episodes, transcripts,
workstreams) in a host-global daemon.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
```

The installer registers the plugin with Claude Code, so a bare `claude` loads it
automatically (or launch with `bcc`, below).

## Why basecamp?

When working with AI coding agents across multiple projects, you face friction:

- **Scattered context** — each project needs different related directories and domain knowledge.
- **Branch conflicts** — parallel sessions on the same repo compete for the working directory.
- **No cross-session memory** — sessions and their transcripts vanish when they close.

basecamp addresses this as a Claude Code plugin that:

1. **Injects project awareness** — an MCP context server detects the configured project from the repo you launch in and surfaces its related directories and curated context.
2. **Runs a persistent hub daemon** — records every session, its episodes, and its full transcript (main thread + subagent sidecars) for cross-session continuity.
3. **Stages isolated work** — the copilot workflow provisions labeled git worktrees and durable workstream records for coordinated, hand-off-able work.
4. **Delivers a shared engineering doctrine** — installed into your home `~/.claude/CLAUDE.md` so it reaches the main session and every subagent.

## What ships

The repo ships two intertwined artifacts:

- **The Claude Code plugin** (`claude/`) — the container Claude Code loads: the plugin manifest, the MCP server registration (`.mcp.json`), the lifecycle hooks (`hooks/hooks.json`), the prompts, the skills, thin `bin/` shims, and a docker harness. Its own design record is [`claude/README.md`](claude/README.md).
- **The `basecamp` Python distribution** (`src/basecamp/`) — the CLI and launcher plus the MCP server, the hooks, the hub daemon, and the config/workspace backends the plugin's shims exec.

## Installation

Requires [uv](https://docs.astral.sh/uv/), `git`, and [Claude Code](https://claude.com/claude-code).

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py          # tool install + register the plugin + install doctrine + seed config
```

`uv run install.py` (equivalently `make install`) does the full bootstrap: it
`uv tool install`s the `basecamp` snapshot onto PATH, records the checkout as the
plugin source, then registers the plugin with Claude Code, installs the home
doctrine block, and seeds the default config. Re-run the wiring at any time — for
example after editing the plugin — with:

```bash
basecamp install           # re-register the plugin, refresh the doctrine block, ensure config
```

`install.py` installs a **non-editable** snapshot on PATH. For live iteration
against your working tree, run the CLI via `uv run basecamp <cmd>` instead of
re-installing after each change.

If `basecamp` isn't on your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrading / uninstalling

```bash
uv tool upgrade basecamp
uv tool uninstall basecamp
```

## Usage

### Loading the plugin

`basecamp install` registers the plugin with Claude Code for you — it drives the
`claude` CLI (`plugin marketplace add` + `plugin install`), which both records the
plugin in `~/.claude/settings.json` and builds the `~/.claude/plugins/` cache the
loader actually reads. So a bare `claude` auto-loads it: no `--plugin-dir` flag.
Once loaded, the plugin registers the MCP context server, wires the lifecycle
hooks, and exposes the basecamp skills as `/basecamp:<name>`. Re-run
`basecamp install` after editing the plugin to refresh Claude Code's cache.

### Launching with `bcc`

`bcc` launches `claude` with basecamp's per-session system prompt applied to the
main session. Extra arguments pass straight through to `claude`:

```bash
cd ~/code/web-app
bcc                        # launch claude with the basecamp system prompt
bcc --model opus           # extra args pass through to `claude`
```

`bcc` is equivalent to `basecamp claude launch`.

### Skills (in-session)

Namespaced `/basecamp:<name>`, auto-surfaced by description:

| Skill | Purpose |
|-------|---------|
| `python-development` | Python engineering doctrine and references |
| `sql` / `data-warehousing` / `data-analysis` | data engineering guidance |
| `marimo` | marimo notebook authoring |
| `gather` | investigation / discovery |
| `planning` | pre-implementation planning posture |
| `pr` | create or update a pull request |
| `copilot` | the repo copilot workflow (Herdr-guarded) |
| `start-workstream` | attach an execution session to a staged workstream |

## Configuration

basecamp config lives in `~/.pi/basecamp/config.json` — a unified document
holding project definitions, per-repo worktree `environments`, model aliases, and
installer metadata. Basecamp (Python) is its **sole writer**; every change goes
through `basecamp config …`.

### Projects

```bash
basecamp config project              # interactive menu (list / add / edit / remove)
basecamp config project list
```

A project maps a `repo_root` (relative to `$HOME`) to related directories and
curated context. When you launch in a repo whose root matches a configured
`repo_root`, the MCP server surfaces that project's context:

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in the injected context |
| `description` | No | Shown in `basecamp config project` listings |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/context/{name}.md` for project context |

User context overrides live under `~/.pi/basecamp/context/`. (The `~/.pi` prefix
is legacy naming kept for runtime state; basecamp has no Pi dependency.)

## Git Worktrees & environments

Worktrees live at `~/.worktrees/<org>/<name>/<label>/` — outside the repo, keyed
by the canonical `<org>/<name>` identity (derived from the origin remote URL,
falling back to the git basename). Git is the source of truth for worktree
registration; basecamp keeps no parallel registry.

A fresh worktree contains tracked files only — gitignored artifacts (`.venv`,
`node_modules`, `.env`, build output) are absent. To provision newly created
worktrees, configure a per-repo **environment**: a setup command keyed by the
canonical repo identity.

```bash
basecamp config env                          # interactive menu (list / add / edit / remove)
basecamp config env list
basecamp config env set <org>/<name> "uv sync && npm ci"
basecamp config env remove <org>/<name>
```

Environments are stored under the `environments` section of
`~/.pi/basecamp/config.json`, keyed by `<org>/<name>`:

```json
{ "environments": { "acme/basecamp": { "setup": "uv sync && npm ci" } } }
```

basecamp ships no default — a repo with no environment is a clean no-op. For
anything beyond a one-liner, point the command at a script you maintain outside
the repo, e.g. `"bash ~/.pi/basecamp/worktree-setup.sh"`.

## The hub daemon

`basecamp hub` runs a host-global, all-Python service over a Unix domain socket
that persists session lifecycle state (`sessions` + `episodes`), verbatim
transcript content (`transcript_nodes` — main thread and every subagent sidecar),
and workstream coordination records. The plugin's lifecycle hooks talk to it; it
is ensured lazily and never a prerequisite for a session to run.

## Development

- **Python** 3.12+, managed with `uv`. There is no Node/TypeScript toolchain.
- **Lint**: `make lint` (`ruff check` + `ruff format --check`).
- **Fix**: `make fix`.
- **Test**: `make test` (`uv run pytest`).
- **File length**: a universal 500-line cap on source files, carried by the engineering doctrine and a non-blocking warn hook (not CI-enforced).

See [AGENTS.md](AGENTS.md) for the architecture and contributor guide.

## License

Apache 2.0
