# basecamp

Multi-project workspace launcher for AI coding agents. Configures project directories, manages isolated git worktrees, and provides semantic memory over past sessions.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi --project basecamp
```

## Why basecamp?

When working with AI coding agents across multiple projects, you face friction:

- **Scattered context** — Each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — Parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — Re-configuring directories and prompts for each session

basecamp solves this with a pi extension that:

1. **Replaces the default system prompt** — Full control over behavior, consistency across sessions, tailored to your workflow
2. **Configures project context** — Loads project-specific prompts and working styles automatically
3. **Supports isolated worktrees** — Use `--label <label>` to work in a labeled worktree for parallel conversations
4. **Manages multi-repo projects** — Groups related repositories under one project definition

## Installation

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/mariozechner/pi-coding-agent).

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py           # interactive (prompts for editable mode)
uv run install.py -e        # editable (recommended for development)
uv run install.py --no-editable
```

This installs two tools (`basecamp` and `observer`) and saves the install directory to `~/.basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, scaffold dirs, create default config
```

If `basecamp` or `observer` aren't in your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrading

```bash
uv tool upgrade basecamp-core && uv tool upgrade basecamp-observer
```

### Uninstalling

```bash
uv tool uninstall basecamp-core && uv tool uninstall basecamp-observer
```

## Usage

### Launching Sessions

Sessions are launched via `pi` with basecamp flags:

```bash
pi --project <project>               # Launch in project's primary directory
pi --project <project> --label <l>   # Work in labeled worktree (creates if new)
pi --project <project> --style eng   # Override working style
```

### Managing Projects

```bash
basecamp project list                    # List available projects
basecamp project add                     # Interactively add a new project
basecamp project edit <name>             # Interactively edit a project
basecamp project remove <name>           # Remove a project
```

### Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/open` | Open project directories in VS Code |
| `/handoff` | Generate session handoff for continuing work |
| `/agents` | Browse available agent definitions |
| `/pull-request` | Create or update a pull request |
| `/pr-comments` | Address PR review comments |
| `/pr-walkthrough` | Generate PR walkthrough |

### Subagents

Dispatch subagents from within a session using the `agent` tool:

```
agent("scout", "Investigate the auth module")
agent("worker", "Fix the login bug")
```

Built-in agents: `scout`, `planner`, `reviewer`, `worker`, `security-reviewer`, `test-reviewer`, `docs-reviewer`, `simplification-reviewer`.

Custom agents can be defined as markdown files in `.basecamp/agents/` (project) or `~/.basecamp/agents/` (user).

## Configuration

Projects are defined in `~/.basecamp/config.json`:

```json
{
  "projects": {
    "web-app": {
      "dirs": ["GitHub/web-app"],
      "description": "Main web application",
      "working_style": "engineering"
    },
    "data-pipeline": {
      "dirs": ["GitHub/pipeline", "GitHub/pipeline-config"],
      "description": "ETL pipeline and configuration",
      "working_style": "engineering",
      "context": "pipeline"
    }
  }
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `dirs` | Yes | Paths relative to `$HOME`. First is primary (cwd), rest are additional context |
| `description` | No | Shown in `basecamp project list` |
| `working_style` | No | Loads matching working style prompt (see below) |
| `context` | No | Loads `~/.basecamp/prompts/context/{name}.md` for project context |

## Prompt System

basecamp replaces the default system prompt via a `before_agent_start` hook. This gives you:

- **Full control** — Define how the agent approaches work, not defaults
- **Consistency** — Same behavior across sessions; immune to upstream prompt changes
- **Customization** — Prompts designed for your specific workflow

Pi's tool definitions and skill listings are sourced dynamically and included in the assembled prompt.

### Prompt Assembly

The system prompt is assembled from layered sources:

```
Runtime context (paths, platform, date)
         ↓
environment.md (CLI usage, Python/uv)
         ↓
working_styles/{name}.md (if configured)
         ↓
system.md (working principles, tools, agents)
         ↓
project context (if configured)
         ↓
tools + skills (dynamically sourced from pi)
```

Override `system.md` by placing a file at `~/.basecamp/prompts/system.md`.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, quest-based work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |

Create custom working styles in `~/.basecamp/prompts/working_styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.basecamp/prompts/context/`. The `context` field in project config points to this file.

Single-repo projects typically use `CLAUDE.md` in the repo itself.

## Git Worktrees

Use `--label <label>` to work in an isolated git worktree for parallel conversations:

```bash
pi --project myproject --label auth      # Create or re-enter "auth" worktree
pi --project myproject --label bugfix    # Create or re-enter "bugfix" worktree
```

Worktrees live in `~/.worktrees/<repo>/<label>/` with branches named `wt/<label>`.

- Worktrees are opt-in via `--label <label>` flag
- Label is both the directory name and worktree identifier
- `/open` in-session opens the worktree directory in VS Code
- Secondary directories stay on the main branch
- Only works with git repositories

## Extension

All skills, agents, hooks, and system prompts are bundled in a single pi extension at `extension/`.

## License

Apache 2.0
