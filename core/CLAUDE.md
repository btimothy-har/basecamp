# core/CLAUDE.md

## What is basecamp-core

The CLI tool. Manages project configuration, assembles system prompts, and launches Claude Code sessions with the right context.

## Key Flows

### Launch Pipeline

`cli/launch.py` → `execute_launch()`:
1. Resolve project config → expand `dirs` to absolute paths
2. Handle worktree if `-l <label>` provided (`get_or_create_worktree`)
3. Load `.env` from primary directory
4. Assemble system prompt (runtime preamble + working style + system.md)
5. Persist assembled prompt to `~/.basecamp/prompts/assembled/{key}.md`
6. Set `BASECAMP_*` environment variables, forward through terminal multiplexer
7. `os.execvp("claude", ...)` — basecamp process is replaced by Claude

### Prompt Assembly

`prompts/system.py` → `build_system_prompt()`:
1. `build_runtime_preamble()` — `<env>` block (paths, platform, date, scratch dir) + `environment.md` + git status
2. `working_styles.load(name)` — user override dir checked first, then package `_working_styles/`
3. `_load_system_prompt()` — user override checked first, then package `_system_prompts/system.md`

Project context (`~/.basecamp/prompts/context/{name}.md`) is NOT assembled into the system prompt. It's injected by the companion SessionStart hook using the `BASECAMP_CONTEXT_FILE` env var.

### Dispatch

`cli/dispatch.py` — runs from within a Claude session:
1. Validate multiplexer available + `CLAUDE_SESSION_ID` + `BASECAMP_TASKS_DIR` set
2. Create `$BASECAMP_TASKS_DIR/{name}/` with `launch.sh`
3. Forward all `BASECAMP_*` env vars to new pane
4. Wait up to 15s for worker to write `session_id` file (set by companion hook)

### Worktree Lifecycle

`git/worktrees.py` — `get_or_create_worktree()` is the main entry point:
- Creates branch `wt/<label>` from current HEAD
- Stores metadata in `.meta/<label>.json`
- `list_worktrees()` auto-cleans orphaned metadata (worktree removed outside basecamp)
- `remove_worktree()` deletes git worktree + metadata + branch
- All git operations have a 30-second timeout

## Design Decisions

### `execvp` replaces the process

The basecamp process is replaced by Claude, not a parent of it. No process to manage, no signal forwarding, Claude inherits the exact environment. The trade-off: nothing runs after launch — post-session work happens via companion hooks.

### Settings use file-level locking

`Settings` wraps `~/.basecamp/config.json` with `fcntl.flock` to prevent corruption from concurrent sessions. Multiple `basecamp claude` invocations and dispatch workers can run simultaneously. The lock is held only during read/write, not for the session lifetime.

### Dispatch generates launcher scripts

Dispatch writes a `launch.sh` script rather than passing arguments directly to the multiplexer. This avoids shell quoting issues when forwarding prompts and paths through tmux/Kitty command injection. The script reads prompt files from disk rather than embedding them inline.

### Worktree metadata lives outside git

Worktree info is stored in `~/.worktrees/<repo>/.meta/<label>.json`, not in the worktree directory. This keeps the working copy clean. The `WORKTREES_DIR` constant is defined in `git/worktrees.py`, not `constants.py`.

### Prompt paths use underscore prefixes

Package defaults live in `_system_prompts/` and `_working_styles/` — Python packaging convention signaling internal package data. User overrides in `~/.basecamp/prompts/` don't use the prefix.

### The "basecamp" project is special

Hardcoded during `basecamp setup` to point at the install directory. Protected from editing/removal via the CLI. Ensures there's always a working project for bootstrapping.

