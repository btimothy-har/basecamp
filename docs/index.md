# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and supports workflow automation.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

## Why basecamp?

Working with AI coding agents across multiple projects brings friction:

- **Scattered context** — each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — re-configuring directories and prompts for each session

Basecamp solves this with a Pi extension that:

1. **Replaces the default system prompt** — full control over behavior, consistency across sessions, tailored to your workflow
2. **Configures project context** — detects configured projects from the repo you launch Pi in and loads project-specific prompts automatically
3. **Supports isolated worktrees** — planning starts in the protected repo root; approved implementation work activates a labeled worktree
4. **Manages multi-repo projects** — groups related repositories under one project definition
5. **Keeps source files focused** — supplies soft per-type limits and a hidden, non-blocking reminder after oversized structured edits

## Next steps

See the **Getting Started** guide for installation and your first session, then **Using basecamp** for slash commands, worktrees, review, and agents.
