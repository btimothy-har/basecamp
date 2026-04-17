# core/AGENTS.md

## What is basecamp-core

The CLI tool. Manages project configuration and environment setup. Session launching, prompt assembly, worktree management, and agent dispatch have moved to the pi extension (`extension/`).

## CLI Commands

- `basecamp setup` — check prerequisites, scaffold directories, create default config
- `basecamp project list` — list configured projects
- `basecamp project add` — interactively add a new project
- `basecamp project edit <name>` — interactively edit a project
- `basecamp project remove <name>` — remove a project

## Key Modules

- `config/project.py` — `ProjectConfig` model, `load_config()`/`save_config()` backed by `settings.py`
- `config/directories.py` — directory resolution and home-relative path conversion
- `settings.py` — file-backed `~/.basecamp/config.json` access with `fcntl.flock` for concurrent safety
- `cli/setup.py` — environment scaffolding (checks for `uv`, `pi`, creates directories)
- `cli/project.py` — interactive project CRUD via `questionary`

## Design Decisions

### Settings use file-level locking

`Settings` wraps `~/.basecamp/config.json` with `fcntl.flock` to prevent corruption from concurrent reads/writes. The lock is held only during read/write, not for the session lifetime.

### Worktree metadata lives outside git

Worktree info is stored in `~/.worktrees/<repo>/.meta/<label>.json`, not in the worktree directory. This keeps the working copy clean. Worktree CRUD is handled by `extension/core/src/worktree.ts`.

### The "basecamp" project is special

Hardcoded during `basecamp setup` to point at the install directory. Protected from editing/removal via the CLI. Ensures there's always a working project for bootstrapping.
