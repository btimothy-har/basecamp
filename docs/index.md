# basecamp

An opinionated harness for AI coding agents, built as a [Pi](https://github.com/earendil-works/pi) extension. A model on its own is raw energy — powerful but undirected. basecamp is the scaffold that focuses it into work, shaping every session with its own prompt, posture, guardrails, and dispatch.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

## What's in it

- **Modular system prompt** — fully replaced and layered (mode, posture, style, voice, craft, environment, capabilities, project context); each piece overridable
- **Cross-repo context** — groups related repositories into one project and loads their config, working style, and `AGENTS.md`
- **Worktree management** — disposable, isolated worktrees so parallel sessions don't fight over the working directory
- **Agent swarms** — scouts, reviewers, and workers dispatched into their own workspaces and merged back as branches

## Read more

- [Getting started](getting-started/installation.md) — install and your first session
- [Using basecamp](using/slash-commands.md) — commands, worktrees, diff review, subagents, the dashboard
- [Configuration](configuration/projects.md) — projects, worktree environments, model aliases
- [Architecture](architecture/core.md) — how the prompt, dispatch, worktrees, guardrails, and hub fit together
