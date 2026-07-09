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
uv run install.py           # interactive (prompts for editable mode)
uv run install.py -e        # editable (recommended for development)
uv run install.py --no-editable
```

This installs the Python tool `basecamp`, prompts for optional Basecamp Pi package groups, and saves installer metadata to `~/.pi/basecamp/config.json`.

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
basecamp projects
```

Use it to list, add, edit, or remove configured projects.

### Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/show-plan` | Show the current plan and task progress |
| `/worktree [label]` | Switch to an existing Git-registered worktree |
| `/create-pr` | Create or update a pull request |
| `/code-review` | Run an independent multi-agent review of the current branch |
| `/title [text]` | Generate a session title from the conversation, or set one manually |
| `/model-aliases` | Manage model aliases (list, add, edit, remove) |

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

Projects are defined in `~/.pi/basecamp/workspace/projects.json`:

```json
{
  "version": 1,
  "projects": {
    "web-app": {
      "repo_root": "GitHub/web-app",
      "additional_dirs": [],
      "description": "Main web application",
      "working_style": "engineering"
    },
    "data-pipeline": {
      "repo_root": "GitHub/pipeline",
      "additional_dirs": ["GitHub/pipeline-config"],
      "description": "ETL pipeline and configuration",
      "working_style": "engineering",
      "context": "pipeline"
    }
  }
}
```

Root `~/.pi/basecamp/config.json` holds installer-owned metadata (`install_dir`, `installed_modules`) and per-repo worktree `environments` (see [Worktree environments](#worktree-environments)); it does not contain project definitions.

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in `basecamp projects` listings |
| `working_style` | No | Loads matching working style prompt (see below) |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/workspace/context/{name}.md` for project context |

Existing local config files with the older project directory schema are migrated to `repo_root` and `additional_dirs` by setup/projects flows.

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

Built-in prompt files can be overridden by creating matching files under `~/.pi/basecamp/workspace/prompts/` (for example, `~/.pi/basecamp/workspace/prompts/environment.md` or `~/.pi/basecamp/workspace/prompts/modes/executor.md`).

### Session Modes

The session mode sets the agent's posture and is shown in the footer. Cycle between `analysis`, `explore` (planning), `supervisor`, and `executor` with shift+tab.

`copilot` is a locked, launch-only mode: start it with `pi --copilot`. It is immutable — shift+tab can neither enter nor leave it — and the `plan()` handoff is disabled in it (a copilot session stages execution-ready workstreams with `launch_workstream` instead of implementing in-session). `pi --copilot` takes precedence over `pi --workstream` if both are passed.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles as `{name}.md` files in `~/.pi/basecamp/workspace/styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.pi/basecamp/workspace/context/`. The `context` field in project config is the file stem only; Basecamp appends `.md` when loading the matching file.

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
basecamp environments                       # interactive menu (list / add / edit / remove)
basecamp environments list
basecamp environments set <org>/<name> "uv sync && npm ci"
basecamp environments remove <org>/<name>
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
- `src/basecamp/` — the single `basecamp` Python distribution (one ordinary src-layout package): setup/projects/install CLI plus the `core`, `workspace`, `swarm` (daemon), and `companion` (TUI) subpackages
- `claude/` — reserved for a future Claude Code launcher

## License

Apache 2.0
