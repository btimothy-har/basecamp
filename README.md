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

This installs the Python tools `basecamp` and `pi-memory`, registers the Pi packages in `pi-extension/` and `pi-memory/`, and saves the Basecamp install directory to `~/.pi/basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, create styles/context dirs, create default config
```

If `basecamp` or `pi-memory` aren't in your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrading

```bash
uv tool upgrade basecamp
uv tool upgrade pi-memory
```

### Uninstalling

```bash
uv tool uninstall basecamp
uv tool uninstall pi-memory
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
| `/plan` | Create a reviewed implementation plan and activate an execution worktree when approved |
| `/show-plan` | Show the current plan and task progress |
| `/tasks` | Show the current goal and task list |
| `/worktree [label]` | Switch to an existing Git-registered worktree |
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

Use ad-hoc dispatch for one-off subagent tasks that do not need a built-in agent definition.

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
| `context` | No | Stem only (no `.md`); loads `~/.pi/context/{name}.md` for project context |

Existing local config files with the older project directory schema are migrated to `repo_root` and `additional_dirs` by setup/config flows.

### Pi memory interpretation

`pi-memory` session interpretation uses PydanticAI at runtime. Configure `interpretation_model` with any PydanticAI-supported model string before running interpretation jobs.

Inspect the current settings:

```bash
pi-memory config
pi-memory config --json
```

Set the session interpretation model:

```bash
pi-memory config --interpretation-model anthropic:claude-sonnet-4-6
```

Tool activity summarization can use a smaller/faster model. If unset, it falls back to the interpretation model:

```bash
pi-memory config --tool-summary-model anthropic:claude-haiku-4-5
pi-memory config --tool-summary-concurrency 25
```

Environment overrides are inherited by dispatcher-spawned `run-job` child processes:

```bash
export PI_MEMORY_INTERPRETATION_MODEL=anthropic:claude-sonnet-4-6
export PI_MEMORY_TOOL_SUMMARY_MODEL=anthropic:claude-haiku-4-5
export PI_MEMORY_TOOL_SUMMARY_CONCURRENCY=25
```

`PI_MEMORY_TOOL_SUMMARY_CONCURRENCY` controls the bounded window of independent one-tool summary calls. The default is conservative (`10`); valid values are `1` through `100`.

When interpretation jobs run, `pi-memory` first stores raw transcript rows canonically in SQLite, then derives chronological `activity_units.activity_text` for downstream model prompts. Raw `transcript_entries.raw_line` remains the source of truth. Tool call/result pairs are summarized one at a time by the configured tool-summary model; session interpretation consumes the cleaned chronological activity text plus citation ids, not raw JSON transcript lines. `pi-memory` does not store API keys. Configure provider credentials with the environment variables expected by PydanticAI/provider packages, such as `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

Clear persisted settings:

```bash
pi-memory config --clear-interpretation-model
pi-memory config --clear-tool-summary-model
pi-memory config --clear-tool-summary-concurrency
```

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

Built-in prompt files can be overridden by creating matching files under `~/.pi/prompts/` (for example, `~/.pi/prompts/environment.md` or `~/.pi/prompts/modes/executor.md`).

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles as `{name}.md` files in `~/.pi/styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.pi/context/`. The `context` field in project config is the file stem only; Basecamp appends `.md` when loading the matching file.

Single-repo projects typically use `AGENTS.md` in the repo itself.

## Git Worktrees

Before a worktree is active, the effective working directory is where you launched Pi; the repository root is the protected checkout boundary for workspace guards. When an implementation plan is approved, Basecamp uses the workspace service to prompt for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

The workspace service owns the `~/.worktrees/<repo>/<label>/` storage convention, `wt/<label>` default branch names, and `/tmp/pi/<repo>` scratch directories. Git is the source of truth for worktree registration; Basecamp consumes workspace state for project context and exposes `BASECAMP_*` env vars to child processes and integrated services.

- The protected checkout must be on the default branch with a clean working tree before activation
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation, preserving the launch subdirectory when applicable
- Mutating `safe_git` commands are blocked unless the effective cwd is inside the active execution worktree
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- Resumed/reloaded/forked sessions restore their last active worktree when still in the same repo
- `/worktree [label]` switches the active worktree during a resumed session
- Use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean up worktrees
- Additional directories stay on their configured checkouts throughout the session
- Only works with git repositories

## Semantic Memory

`pi-memory` is the active memory subsystem. It runs a local Python service for canonical transcript capture, durable job processing, raw recall, deterministic episode structure, activity-text projection, tool activity summarization, session interpretation, interpretation quality reports, durable memory promotion, and rebuildable semantic projection. Pi integration stays thin: the Pi package starts or reconnects to the local service and delegates memory behavior to the service.

The former `pi-observer` subsystem is deprecated and no longer installed, registered, tested, or documented as a user workflow. Historical observer stores are not required by `pi-memory`.

### How it works

1. **Serve** — `pi-memory serve` runs the local FastAPI service backed by SQLite and service-owned durable jobs.
2. **Observe** — `pi-memory observe` or the HTTP observe endpoint records transcript observations, stores transcript deltas canonically, and enqueues processing jobs when new entries are available.
3. **Process** — Durable jobs derive raw recall indexes, deterministic episode/activity structure, tool activity summaries, session interpretations, quality reports, projection records, and durable memory candidates.
4. **Recall** — Raw transcript recall is available today; unified recall over session claims and durable memory projection is the next service-backed recall surface.

### pi-memory CLI

```bash
pi-memory serve             # Run the local memory service
pi-memory status            # Show service status
pi-memory config            # Inspect persisted model/concurrency settings
pi-memory observe PATH      # Record a transcript observation
```

### Storage

All active memory data is local to `pi-memory`:

- `~/.pi/memory/memory.db` — canonical transcript, job, recall, episode, activity-text, interpretation, quality, projection, and durable-memory store
- `~/.pi/memory/config.json` — model/concurrency settings
- `~/.pi/basecamp/config.json` — Basecamp settings, including the installed repo path

## Package Layout

basecamp is split into root-level products:

- `basecamp-cli/` — Python package for the `basecamp` setup/config CLI
- `pi-extension/` — Pi package for project context, session UI, worktrees, workflow, git, and engineering skills
- `pi-memory/` — Python and Pi package for the active local memory service, transcript capture, jobs, raw recall, episode structure, session interpretation, quality reports, durable memory, and semantic projection

`pi-observer/` contains deprecated historical memory code and is excluded from active install, test, lint, and package-registration workflows.

## License

Apache 2.0
