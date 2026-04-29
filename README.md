# basecamp

Multi-project workspace launcher for AI coding agents. Configures project directories, manages isolated git worktrees, and provides semantic memory over past sessions.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
bpi basecamp
```

## Why basecamp?

When working with AI coding agents across multiple projects, you face friction:

- **Scattered context** — Each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — Parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — Re-configuring directories and prompts for each session

basecamp solves this with a pi extension that:

1. **Replaces the default system prompt** — Full control over behavior, consistency across sessions, tailored to your workflow
2. **Configures project context** — Loads project-specific prompts and working styles automatically
3. **Supports isolated worktrees** — Planning starts in the protected checkout; approved implementation work activates a labeled worktree
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

This installs two tools (`basecamp` and `observer`) and saves the install directory to `~/.pi/basecamp/config.json`.

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

Sessions are launched through basecamp/pi in the protected primary checkout. Worktrees are selected later, when an implementation plan is approved.

```bash
bpi <project>             # Launch in project's primary directory
bpi .                     # Launch in the current git repo
bpi <project> --style eng # Override working style
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

Built-in agents: `scout`, `worker`, `security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`.

Custom agents can be defined as markdown files in `~/.pi/agents/` (user-level).

## Configuration

Projects are defined in `~/.pi/basecamp/config.json`:

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
| `context` | No | Loads `~/.pi/context/{name}.md` for project context |

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

Override `system.md` by placing a file at `~/.pi/prompts/system.md`.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles in `~/.pi/styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.pi/context/`. The `context` field in project config points to this file.

Single-repo projects typically use `AGENTS.md` in the repo itself.

## Git Worktrees

Basecamp starts sessions in the protected primary checkout for planning and discovery. When an implementation plan is approved, Basecamp prompts for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

Worktrees live in `~/.worktrees/<repo>/<label>/` with branches named `wt/<label>` by default. Git is the source of truth for worktree registration; Basecamp does not maintain a separate metadata registry.

- The protected checkout must be on the default branch with a clean working tree before activation
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- `/worktree [label]` switches the active worktree during a resumed session
- `/open` in-session opens the active worktree directory in VS Code
- Use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean up worktrees
- Secondary directories stay on their configured checkouts throughout the session
- Only works with git repositories

## Semantic Memory (Observer)

basecamp-observer provides semantic memory across sessions. It ingests session transcripts, extracts structured knowledge via LLM, and makes it searchable.

### How it works

1. **Ingest** — A hook triggers `observer ingest` at session end, parsing new transcript events incrementally
2. **Process** — A background job refines events into work items, extracts structured artifacts (summary, knowledge, decisions, constraints, actions), and embeds them into ChromaDB
3. **Search** — The `recall` skill provides hybrid search (semantic + keyword) with time-decay scoring, scoped to the current project

### Observer CLI

```bash
observer setup                         # Initialize database and config
observer db status                     # Show database and index status
observer db migrate                    # Run pending schema migrations
observer config set mode on            # Enable full pipeline (default: on)
observer config set mode off           # Ingestion only, no LLM processing
```

### Storage

All data is local — no servers or external services:
- `~/.pi/observer/observer.db` — SQLite (relational model + FTS5 keyword search)
- `~/.pi/observer/chroma/` — ChromaDB (vector embeddings, HNSW index)
- `~/.pi/observer/config.json` — Observer settings

## Extension

All skills, agents, hooks, and system prompts are bundled in a single pi extension at `pi-ext/`.

## License

Apache 2.0
