# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and supports workflow automation.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

## Why basecamp?

When working with AI coding agents across multiple projects, you face friction:

- **Scattered context** — Each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — Parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — Re-configuring directories and prompts for each session

basecamp solves this with a Pi extension that:

1. **Replaces the default system prompt** — Full control over behavior, consistency across sessions, tailored to your workflow
2. **Configures project context** — Detects configured projects from the repo you launch Pi in and loads project-specific prompts automatically
3. **Supports isolated worktrees** — Planning starts in the protected repo root; approved implementation work activates a labeled worktree
4. **Manages multi-repo projects** — Groups related repositories under one project definition

## Installation

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/earendil-works/pi).

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py
```

This installs the Python tool, installs the extension dependencies, registers the repository root as the Basecamp Pi extension, and saves installer metadata to `~/.pi/basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, create workspace dirs, create default project config
```

If `basecamp` isn't in your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrading

```bash
uv tool upgrade basecamp
```

### Uninstalling

```bash
uv tool uninstall basecamp
```

## Usage

### Launching Sessions

Launch sessions with plain Pi from the repo or subdirectory you want to work in. Basecamp detects the git repository root and loads the matching project when its `repo_root` is configured.

```bash
cd ~/GitHub/web-app
pi                         # Detects project by repo_root

cd ~/GitHub/web-app/src/api
pi                         # Also detects the same project from the git root

pi --style advisor         # Optional working style override
```

If the launch cwd's git root does not match a configured `repo_root`, Basecamp starts an unprojected Pi session.

### Managing Projects

Project configuration is managed through the projects menu:

```bash
basecamp config project
```

Use the menu to list, add, edit, or remove configured projects. Scriptable subcommands are available under the same group, such as `basecamp config project list`.

### Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/show-plan` | Show the current plan and task progress |
| `/worktree [label]` | Switch to an existing Git-registered worktree |
| `/create-pr` | Create or update a pull request |
| `/code-review` | Run an independent multi-agent review of the current branch |
| `/title [text]` | Generate a session title from the conversation, or set one manually |
| `/model-aliases` | Manage model aliases (list, add, edit, remove) |

### Browser Automation

Primary sessions can load the `playwright-cli` skill to automate an installed Chrome or Brave browser. Basecamp uses an exact-pinned local CLI through its gated `playwright-cli` command—no global install, browser download, or MCP server is required. Accessibility snapshots and element refs are the default interaction loop; screenshots are written outside the repository and then inspected with Pi's `read` tool.

Playwright starts with a fresh managed persistent profile, and browser artifacts default to the private bounded directory `~/.pi/basecamp/browser/playwright-output`. Set `BASECAMP_BROWSER_PATH` for a custom Chromium executable; explicit `PLAYWRIGHT_MCP_*` environment overrides are also honored. Browser access is not exposed to subagents. Upgrades do not migrate or delete the former `~/.pi/basecamp/browser/profile`.

### Subagents

Use the `agents` skill for agent selection and async daemon dispatch guidance:

```js
skill({ name: "agents" })
dispatch_agent({ agent: "scout", task: "Investigate the auth module" }) // returns an agent handle
list_agents({ awaitable: true })
wait_for_agent({ handles: "<agent-handle>" })
```

Built-in agents: `scout`, `worker`, `devils-advocate`, `security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`.

Named read-only agents may fan out for parallel investigation and review. Be conservative with `worker`: do not parallelize `worker` against the same worktree until daemon mutation leases exist.

## Configuration

Basecamp’s machine-readable configuration is one locked JSON document at `~/.pi/basecamp/config.json`. Python is the sole writer; the Pi extension reads it in-process. Manage it interactively with `basecamp config`, through typed `project`/`env`/`alias` subcommands, or with generic `show|get|set|unset|edit` commands.

```json
{
  "version": 1,
  "install_dir": "/Users/me/src/basecamp",
  "projects": {
    "web-app": {
      "repo_root": "GitHub/web-app",
      "additional_dirs": [],
      "description": "Main web application",
      "working_style": "engineering",
      "context": null
    }
  },
  "environments": {
    "acme/web-app": {"setup": "uv sync && npm ci"}
  },
  "model_aliases": {
    "fast": "claude-haiku-4-5"
  },
  "logseq": {
    "graph_dir": "~/logseq"
  }
}
```

Project fields:

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in project listings |
| `working_style` | No | Loads a matching working-style prompt |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/context/{name}.md` |

User-authored prompt customizations live beside the config in `~/.pi/basecamp/context/`, `styles/`, and `prompts/`.

### Local-state doctor

`basecamp doctor` is read-only. It checks the current config and directory layout, known retired paths, hub liveness, SQLite integrity, and the Store’s expected schema/invariants. Repairable findings and errors produce exit status 1; informational findings and warnings do not.

```bash
basecamp doctor
basecamp doctor --repair
```

`--repair` applies only bounded, non-destructive repairs. It locks and backs up config before rewriting it, migrates non-conflicting prior config/layout data, archives clean-break artifacts without importing them, and runs the existing Store migrations only when the hub is conclusively stopped. Changed config and databases, plus retired artifacts removed from the active layout, are retained under one private timestamped recovery archive:

```text
~/.pi/basecamp/backups/doctor/<timestamp>/
```

The doctor never resets current records, overwrites conflicts, follows symlinks, drops unknown state, terminates a daemon, or prunes its archives. Corrupt, newer, and conflicting state remains in place with an actionable error. Ambiguous daemon liveness is a read-only warning and blocks the affected repair. The former browser profile at `~/.pi/basecamp/browser/profile` is explicitly excluded.

Older standalone project/alias files and `workspace/{context,styles,prompts}` are handled by `--repair`; the standalone `migrations/001_consolidate_basecamp_state.py` script records an earlier one-shot consolidation and is not the current repair surface.

## Prompt System

basecamp replaces the default system prompt via a `before_agent_start` hook. This gives you:

- **Full control** — Define how the agent approaches work, not defaults
- **Consistency** — Same behavior across sessions; immune to upstream prompt changes
- **Customization** — Prompts designed for your specific workflow

Pi's tool definitions and skill listings are sourced dynamically and included in the assembled prompt.

### Prompt Assembly

The system prompt is assembled from layered sources:

```
mode prompt, plus read-only constraints when applicable
         ↓
working style prompt, or subagent prompt for dispatched agents
         ↓
environment.md (CLI usage, Python/uv)
         ↓
capabilities index (tools, skills, and parent-session agents)
         ↓
project context (configured context plus AGENTS.md/CLAUDE.md)
         ↓
runtime environment (paths, platform, date, git/worktree state)
```

Built-in prompt files can be overridden by creating matching files under `~/.pi/basecamp/prompts/` (for example, `~/.pi/basecamp/prompts/environment.md` or `~/.pi/basecamp/prompts/modes/work.md`).

### Session Modes

The session mode sets the agent's posture and is shown in the footer. Cycle between `analysis`, `explore` (planning), and `work` (the default) with shift+tab. Dispatched subagents are read-only; the primary session is the sole mutator.

`copilot` is a locked, launch-only mode: start it with `pi --copilot`. It is immutable — shift+tab can neither enter nor leave it — and the `plan()` handoff is disabled in it (a copilot session stages execution-ready workstreams with `launch_workstream` instead of implementing in-session). `pi --copilot` takes precedence over `pi --workstream` if both are passed.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles as `{name}.md` files in `~/.pi/basecamp/styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.pi/basecamp/context/`. The `context` field in project config is the file stem only; Basecamp appends `.md` when loading the matching file.

Single-repo projects typically use `AGENTS.md` in the repo itself.

## Git Worktrees

Before a worktree is active, the effective working directory is where you launched Pi; the repository root is the protected checkout boundary for workspace guards. When an implementation plan is approved, Basecamp uses the workspace service to prompt for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

The workspace service owns the `~/.worktrees/<org>/<name>/<label>/` storage convention, `wt/<label>` default branch names, and `/tmp/pi/<org>/<name>` scratch directories. Git is the source of truth for worktree registration; Basecamp consumes workspace state for project context and exposes `BASECAMP_*` env vars to child processes and integrated services.

- The protected checkout must be on the default branch with a clean working tree before activation
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation, preserving the launch subdirectory when applicable
- Mutating `git`/`gh` commands run through the bash reviewer, and edits or git operations are blocked unless the effective cwd is inside the active execution worktree
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- Resumed/reloaded/forked sessions restore their last active worktree when still in the same repo
- `/worktree [label]` switches the active worktree during a resumed session
- Use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean up worktrees
- Additional directories stay on their configured checkouts throughout the session
- Only works with git repositories

### Worktree environments

A fresh worktree contains tracked files only — gitignored artifacts (`.venv`, `node_modules`, `.env`, build output) are absent. To provision newly created worktrees, configure a per-repo **environment**: a setup command keyed by repo name.

```bash
basecamp config env                         # interactive menu (list / add / edit / remove)
basecamp config env list
basecamp config env set <org>/<name> "uv sync && npm ci"
basecamp config env remove <org>/<name>
```

Environments are stored under the `environments` section of `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename) — i.e. `BASECAMP_REPO`:

```json
{ "environments": { "acme/basecamp": { "setup": "uv sync && npm ci" } } }
```

basecamp ships no default — a repo with no environment is a clean no-op. When an approved implementation plan **creates** a new execution worktree, basecamp resolves the current repo's setup command and runs it before handoff:

- Executed as `bash -lc "<command>"` with the working directory set to the new worktree.
- Inherits the `BASECAMP_*` env vars plus `BASECAMP_REPO_ROOT` (the protected checkout path), so the command can copy or symlink artifacts from the source checkout if it chooses. basecamp does not prescribe what the command does.
- **Blocks** activation with a **180-second timeout**; the fresh session starts only once setup finishes.
- **Warn-and-proceed**: a non-zero exit or timeout surfaces a warning and is recorded in the handoff result, but activation and handoff still complete.
- **Creation only**: it does not run when resuming/attaching an existing worktree or switching via `/worktree`.

For anything beyond a one-liner, point the command at a script you maintain outside the repo, e.g. `"bash ~/.pi/basecamp/worktree-setup.sh"`.

## Package Layout

basecamp is organized by the artifacts it ships (design record: `docs/design/repo-rearchitecture.md`):

- `pi/` — the single Pi extension (`pi/extension.ts` + `pi/<domain>/`), registered from the repo root: project context, session UI, worktrees, workflow, git, engineering, agents, and companion features
- `src/basecamp/` — the single `basecamp` Python distribution (one ordinary src-layout package): CLI/setup/install shell plus `core`, `workspace`, `hub` (daemon), `companion` (TUI), and the cross-domain local-state `doctor` feature

## License

Apache 2.0
