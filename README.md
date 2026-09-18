# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and supports workflow automation.

## Quick start

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/earendil-works/pi). Bun is required during installation only when `omp` is missing.

## OMP migration

`bomp` is an additional migration launcher for Basecamp's independent [Oh My Pi](https://github.com/can1357/oh-my-pi) plugin; the Pi quick start above remains the default. Install Basecamp as above; later runs can use `basecamp install`. The shared installer records the source checkout and verifies a PATH-resolved `omp` with `omp --version`. It leaves an existing OMP installation untouched. Only when `omp` is missing does it require Bun and run exactly `bun install -g @oh-my-pi/pi-coding-agent`, then verify the installed command before completing:

```bash
bomp [OMP arguments...]
```

A fresh interactive `bomp` launched from a repository's canonical checkout starts OMP in a temporary detached worktree. Basecamp copies the checkout's staged, unstaged, and nonignored untracked state without changing the source branch, index, or files. A nested `--cwd` starts at the corresponding directory inside the scratch. Explicit and settings-driven session resumes, management, headless, non-interactive, and linked-worktree launches remain direct. `bomp --direct` also requests direct launch explicitly.

The temporary scratch is supervised only for that invocation. On exit, Basecamp removes it when it still matches the launch snapshot or native `/wt` has reset it clean to the pinned commit; a branch-attached scratch, detached commit, changed content, or unverifiable Git state is retained. Run OMP's native `/wt <branch>` to move the session and its changes into a durable branch-backed worktree. OMP's transcript cwd remains the only session/worktree affinity record.

`bomp --detached` retains the older force-discard mode:

```bash
bomp --detached [OMP arguments...]
```

Explicit detached mode requires a clean checkout and force-removes its initial detached worktree on final exit, including changes and detached commits left there. Use `/wt <branch>` before exit to retain work. Any failed removal prints the exact targeted `git -C '<source-root>' worktree remove --force '<initial-worktree>'` recovery command; never substitute the broad `omp worktree clear --all`.

The shared installer also registers Basecamp's standalone workspace reminder extension in the active directory reported by `omp config path`, so plain `omp` receives it too. An interactive canonical checkout warns once. Every Git-backed turn receives the same policy: use the canonical checkout for inspection and planning, treat a detached worktree as writable but temporary, and use `/wt <branch>` before exit to carry the session and changes into a durable branch-backed worktree. The reminder is advisory; OMP tools retain their native behavior.

The remaining Basecamp OMP surface is the PATH-based launcher, the source-checkout-backed `omp/` extension package, and Basecamp's user-level ownership, commit-checkpoint, and code-comment rules. `basecamp install` targets the active native agent directory, including an environment-selected profile, without maintaining a parallel profile or session registry. OMP keeps its default prompt, context discovery, transcript storage, and native session lifecycle; `bomp` does not apply Basecamp's Pi prompt replacement or carry over configured `context` or `working_style`.

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
