# core/CLAUDE.md

## What is basecamp-core

The CLI tool. Manages project configuration, assembles system prompts, and launches Claude Code sessions with the right context.

## Key Flows

### Launch Pipeline

`cli/launch.py` → `execute_launch()`:
1. Resolve project config → expand `dirs` to absolute paths
2. Handle worktree if `-l <label>` provided (`get_or_create_worktree`)
3. Assemble system prompt (runtime preamble + working style + system.md)
4. Persist assembled prompt to `~/.basecamp/.cached/{project}/prompt.md`
5. Build session settings via `build_session_settings()` — loads `.env`, injects `BASECAMP_*` vars, persists to `~/.basecamp/.cached/{project}/settings.json`
6. `exec_session(claude, --settings <settings_file>)` — settings file carries all env vars; no multiplexer forwarding needed

### Prompt Assembly

`prompts/system.py` → `build_system_prompt()`:
1. `build_runtime_preamble()` — `<env>` block (paths, platform, date, scratch dir) + `environment.md` + git status
2. `working_styles.load(name)` — user override dir checked first, then package `_working_styles/`
3. `_load_system_prompt()` — user override checked first, then package `_system_prompts/system.md`

Project context (`~/.basecamp/prompts/context/{name}.md`) is NOT assembled into the system prompt. It's injected via the `BASECAMP_CONTEXT_FILE` env var.

### Worker Dispatch

`cli/worker.py` + `worker/` module — runs from within a Claude session:
1. `basecamp worker create --name X [--model MODEL] [--dispatch]` — reads prompt from stdin (default: sonnet)
2. Creates worker dir in `/tmp/claude-workspace/workers/{project}/{name}/` with `prompt.md` + `launch.sh`
3. Writes entry to persistent index at `~/.basecamp/workers/{project}.json` (file-locked, self-pruning)
4. If `--dispatch`, spawns terminal pane via tmux/Kitty, forwards `BASECAMP_WORKER_DIR` + `BASECAMP_WORKER_NAME`
5. `basecamp worker dispatch --name X` — dispatches a previously staged worker
6. `basecamp worker list [--all]` — lists workers, filtered by current session by default

### Worktree Lifecycle

`git/worktrees.py` — `get_or_create_worktree()` is the main entry point:
- Creates branch `wt/<label>` from current HEAD
- Stores metadata in `.meta/<label>.json`
- `list_worktrees()` auto-cleans orphaned metadata (worktree removed outside basecamp)
- `remove_worktree()` deletes git worktree + metadata + branch
- All git operations have a 30-second timeout

## Design Decisions

### `execvp` replaces the process

The basecamp process is replaced by Claude, not a parent of it. No process to manage, no signal forwarding, Claude inherits the exact environment. The trade-off: nothing runs after launch — post-session work happens via plugin hooks.

### Settings use file-level locking

`Settings` wraps `~/.basecamp/config.json` with `fcntl.flock` to prevent corruption from concurrent sessions. Multiple `basecamp claude` invocations and dispatch workers can run simultaneously. The lock is held only during read/write, not for the session lifetime.

### Worker dispatch generates launcher scripts

Worker creation writes a `launch.sh` script rather than passing arguments directly to the multiplexer. This avoids shell quoting issues when forwarding prompts and paths through tmux/Kitty command injection. The script reads prompt files from disk rather than embedding them inline.

### Worker storage is hybrid: persistent index + ephemeral files

Worker metadata (including session_id) lives in a persistent per-project JSON index (`~/.basecamp/workers/{project}.json`) — the single source of truth for worker state. Runtime files (prompt, launcher script) live in `/tmp/claude-workspace/workers/` so they auto-clean on reboot. The index self-prunes stale entries (whose worker_dir no longer exists) on every read.

### Worker names always include a UUID prefix

Worker names follow the format `worker-{6-char-hex}[-custom-name]`. The hex prefix guarantees uniqueness; the optional suffix provides human-readable intent. This eliminates duplicate name conflicts without requiring existence checks.

### Worktree metadata lives outside git

Worktree info is stored in `~/.worktrees/<repo>/.meta/<label>.json`, not in the worktree directory. This keeps the working copy clean. The `WORKTREES_DIR` constant is defined in `git/worktrees.py`, not `constants.py`.

### Prompt paths use underscore prefixes

Package defaults live in `_system_prompts/` and `_working_styles/` — Python packaging convention signaling internal package data. User overrides in `~/.basecamp/prompts/` don't use the prefix.

### The "basecamp" project is special

Hardcoded during `basecamp setup` to point at the install directory. Protected from editing/removal via the CLI. Ensures there's always a working project for bootstrapping.

