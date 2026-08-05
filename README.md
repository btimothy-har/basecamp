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
