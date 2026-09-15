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

Without `--detached`, `bomp` preserves every user-supplied OMP argument, including `--cwd`, and directly execs OMP. It explicitly loads Basecamp's bundled `omp/` plugin; when launched from a configured Basecamp project's repository, a subdirectory, or a linked worktree, it first prepends configured additional directories that currently exist as native OMP `--add-dir=<absolute-path>` flags.

For a disposable session from the source checkout's current commit:

```bash
bomp --detached [OMP arguments...]
```

Detached mode requires a clean Git checkout and creates a new detached-HEAD worktree at source `HEAD` under OMP's worktree base. A source `--cwd` may select a nested directory; only in detached mode does `bomp` consume it and start OMP at the corresponding path in the new worktree.

When OMP finally exits, `bomp` force-removes the initial checkout, discarding staged, unstaged, untracked, and ignored files plus detached commits. To retain code, run OMP's native `/wt <branch>` before exit; it switches to a branch worktree and moves the live transcript. Chat history otherwise remains ordinary durable OMP history. After cleanup, an ordinary `bomp --resume <id>` lets OMP interactively re-root a transcript whose recorded working directory was removed.

If cleanup fails, `bomp` prints the exact targeted `git -C '<source-root>' worktree remove --force '<initial-worktree>'` recovery command. Use that command; do not run the broad `omp worktree clear --all` command.

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
