# basecamp

Claude Code multi-project workspace launcher with custom prompts and isolated worktrees.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
basecamp start basecamp
```

## Why basecamp?

When working with Claude Code across multiple projects, you face friction:

- **Scattered context** — Each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — Parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — Re-configuring directories and prompts for each session

basecamp solves this with a single command that:

1. **Replaces Claude's default system prompt** — Full control over behavior, consistency across sessions, tailored to your workflow (Claude Code still appends its tool definitions)
2. **Configures project context** — Loads project-specific prompts and working styles automatically
3. **Supports isolated worktrees** — Use `-l <label>` to work in a labeled worktree for parallel conversations
4. **Manages multi-repo projects** — Groups related repositories under one project definition

## Features

### Multi-Project Management

Define projects in `~/.basecamp/projects.json` with their directories, descriptions, and working styles. Launch any project with `basecamp start <project>`.

```json
{
  "my-project": {
    "dirs": ["GitHub/my-project", "GitHub/my-project-docs"],
    "description": "My awesome project",
    "working_style": "engineering"
  }
}
```

### Custom Prompts

Layer prompts for different contexts:

| Layer | Purpose |
|-------|---------|
| **Environment** | CLI context, Python/uv usage, project paths |
| **Core** | Working principles, task management, tool usage |
| **Working Style** | Role definition, communication style, code quality practices |
| **Project Context** | Domain knowledge, project-specific patterns |

### Git Worktree Isolation

Use `-l <label>` to work in an isolated worktree:

```bash
basecamp start myproject -l auth      # Create or re-enter "auth" worktree
basecamp start myproject -l bugfix    # Create or re-enter "bugfix" worktree
```

Worktrees live in `~/.worktrees/<repo>/<label>/` with branches named `wt/<label>`.

## Installation

Requires [uv](https://docs.astral.sh/uv/) and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

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

### Launching Projects

```bash
basecamp start <project>                # Start in project directory
basecamp start <project> --resume       # Resume previous conversation (-r)
basecamp start <project> -l <label>     # Work in labeled worktree (creates if new)
```

### Opening in VS Code

```bash
basecamp open <project>                  # Open basecamp + project directories
basecamp open <project> -n               # Open in new window
basecamp open <project> -l <label>       # Open in existing worktree
```

### Managing Worktrees

```bash
basecamp worktree list <project>         # List worktrees for project
basecamp worktree list --all             # List all worktrees (-a)
basecamp worktree clean <project>        # Interactive cleanup
basecamp worktree clean <project> <name> # Remove specific worktree
basecamp worktree clean <project> --all  # Remove all worktrees
basecamp worktree clean <project> -f     # Force removal (--force)
```

### Listing Projects

```bash
basecamp projects                        # Show available projects
```

## Configuration

Projects are defined in `~/.basecamp/projects.json`:

```json
{
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
```

| Field | Required | Description |
|-------|----------|-------------|
| `dirs` | Yes | Paths relative to `$HOME`. First is primary (cwd), rest are `--add-dir` |
| `description` | No | Shown in `basecamp projects` list |
| `working_style` | No | Loads `~/.basecamp/prompts/working_styles/{name}.md` (user override) or package default |
| `context` | No | Loads `~/.basecamp/prompts/context/{name}.md` for project context |

## Prompt System

basecamp replaces Claude Code's default system prompt via the `--system-prompt` flag. This gives you:

- **Full control** — Define how Claude approaches work, not Anthropic's defaults
- **Consistency** — Same behavior across sessions; immune to upstream prompt changes
- **Customization** — Prompts designed for your specific workflow

Claude Code still appends its own tool definitions section (tool schemas, permissions, MCP servers) which cannot be modified. basecamp controls everything else.

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
```

Override `system.md` by placing a file at `~/.basecamp/prompts/system.md`.

Project context is injected separately via a SessionStart hook, not included in the system prompt. This places the project context alongside any `CLAUDE.md` file in the primary repository.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, quest-based work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |

Create custom working styles in `~/.basecamp/prompts/working_styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.basecamp/prompts/context/`. The `context` field in project config points to this file.

Single-repo projects typically use `CLAUDE.md` in the repo itself.

## Plugins

basecamp includes optional plugins for extended functionality. These are complementary, not required.

| Plugin | Description |
|--------|-------------|
| `bc-collab` | Collaborative discovery and planning for ideation and requirements |
| `bc-eng` | Code review, PR workflows, testing patterns, Python/SQL development |
| `bc-cursor` | Discovers `.cursor/*.mdc` context files |
| `bc-gpg-check` | Verifies GPG card before git commit/tag |

### Installing Plugins

From within a Claude Code session started via basecamp:

```
/plugin marketplace add /path/to/basecamp
/plugin install bc-eng@basecamp
```

The first command registers basecamp as a marketplace (it discovers `.claude-plugin/marketplace.json`). The second installs a plugin from it. Available plugins: `bc-collab`, `bc-cursor`, `bc-eng`, `bc-gpg-check`.

Create custom plugins in `plugins/` following [Claude Code plugin docs](https://docs.anthropic.com/en/docs/claude-code/plugins). Plugins in `plugins/private/` are gitignored.

## License

Apache 2.0
