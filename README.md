# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and supports workflow automation.

## Quick start

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/earendil-works/pi).

## OMP migration

`bomp` is an additional migration launcher for Basecamp's independent [Oh My Pi](https://github.com/can1357/oh-my-pi) plugin; the Pi quick start above remains the default. Install Basecamp as above, then make sure the `omp` command and Bun 1.3.14+ are available:

```bash
bomp [OMP arguments...]
```

`bomp` explicitly loads Basecamp's bundled `omp/` plugin and passes every user argument through unchanged. When launched from a configured Basecamp project's repository, a subdirectory, or a linked worktree, it first prepends configured additional directories that currently exist as native OMP `--add-dir=<absolute-path>` flags.

The migration surface is currently limited to five portable skills (`data-analysis`, `data-warehousing`, `marimo`, `python-development`, and `sql`) and OMP-native file-length reminders. OMP retains its default prompt and context discovery: `bomp` does not apply Basecamp's Pi prompt replacement, carry over configured `context` or `working_style`, or modify OMP configuration.

## What basecamp does

- **Replaces the default system prompt**: full control over agent behavior, consistent across sessions
- **Configures project context**: detects the repo you launch in and loads matching prompts automatically
- **Provisions isolated worktrees**: planning starts in the protected checkout; approved work activates a labeled worktree
- **Manages multi-repo projects**: groups related repositories under one project definition
- **Dispatches subagents**: scouts, reviewers, and workers each in their own isolated workspace
- **Keeps source files focused**: soft per-type caps with a non-blocking reminder after oversized edits

## Documentation

Full documentation lives at **[basecamp.playground.tools](https://basecamp.playground.tools/)**: installation, usage, configuration, and architecture.

The repo's source for the site is under `docs/` (MkDocs Material); `make docs` serves it locally.

## Development

```bash
make test      # uv run pytest + npm test
make lint      # ruff + tsc + biome + import-boundary + file-length
make docs      # local docs server
```

Python 3.12+ with [uv](https://docs.astral.sh/uv/); the Pi extension is TypeScript (`npm run check`). See [AGENTS.md](AGENTS.md) for agent-facing development context and architecture invariants.

## License

MIT
