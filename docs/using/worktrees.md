# Git Worktrees

Before a worktree is active, the effective working directory is where you launched Pi; the repository root is the protected checkout boundary for workspace guards. When an implementation plan is approved, Basecamp uses the workspace service to prompt for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

The workspace service owns the `~/.worktrees/<org>/<name>/<label>/` storage convention and `/tmp/pi/<org>/<name>` scratch directories. Directory labels are deliberately generic (`wt/<slug>`, or `copilot/<slug>` for workstreams) because the worktree is a disposable space; the branch it holds (`<user-prefix>/<session-tag>-<slug>`) is the durable identity of the work. Git is the source of truth for worktree registration; Basecamp consumes workspace state for project context and exposes `BASECAMP_*` env vars to child processes and integrated services.

- The protected checkout must be on the default branch before activation; a dirty checkout does not block it, since worktrees are cut from HEAD and uncommitted checkout changes stay where they are
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation, preserving the launch subdirectory when applicable
- Mutating `git`/`gh` commands run through the bash reviewer, and edits or git operations are blocked unless the effective cwd is inside the active execution worktree
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- Resumed/reloaded/forked sessions restore their last active worktree when still in the same repo
- `/worktree` offers **Create new worktree** (prompts for a slug, provisions and activates it) alongside the list of live worktrees to switch to; `/worktree [label]` switches directly
- Session-owned worktrees remain human-managed; outside Pi, use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean them up
- Additional directories stay on their configured checkouts throughout the session
- Only works with git repositories
