# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and provides semantic memory over past sessions.

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

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/mariozechner/pi-coding-agent).

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py           # interactive (prompts for editable mode)
uv run install.py -e        # editable (recommended for development)
uv run install.py --no-editable
```

This installs `basecamp`, `observer`, and `recall`, registers the Pi extension, and saves the install directory to `~/.pi/basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, scaffold dirs, create default config
```

If `basecamp`, `observer`, or `recall` aren't in your PATH:

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

Project configuration is managed through the interactive menu:

```bash
basecamp config
```

Use the **Projects** section to list, add, edit, or remove configured projects.

### Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/agents` | Browse available agent definitions |
| `/create-pr` | Create or update a pull request |
| `/create-issue` | Draft and publish a GitHub issue through review |
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

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in `basecamp config` project listings |
| `working_style` | No | Loads matching working style prompt (see below) |
| `context` | No | Loads `~/.pi/context/{name}.md` for project context |

The install/setup/config flows migrate legacy `dirs` entries to `repo_root` and `additional_dirs` locally.

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

Before a worktree is active, the effective working directory is where you launched Pi; the repository root is the protected checkout boundary for workspace guards. When an implementation plan is approved, Basecamp uses the workspace service to prompt for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

The workspace service owns the `~/.worktrees/<repo>/<label>/` storage convention, `wt/<label>` default branch names, and `/tmp/pi/<repo>` scratch directories. Git is the source of truth for worktree registration; Basecamp consumes workspace state for project and observer context and does not maintain a separate metadata registry.

- The protected checkout must be on the default branch with a clean working tree before activation
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation, preserving the launch subdirectory when applicable
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- Resumed/reloaded/forked sessions restore their last active worktree when still in the same repo
- `/worktree [label]` switches the active worktree during a resumed session
- Use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean up worktrees
- Additional directories stay on their configured checkouts throughout the session
- Only works with git repositories

## Semantic Memory (Observer)

The `observer` CLI provides semantic memory across sessions. It ingests session transcripts, extracts structured knowledge via LLM, and makes it searchable.

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
