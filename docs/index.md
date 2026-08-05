# basecamp

An opinionated harness for AI coding agents, built as a [Pi](https://github.com/earendil-works/pi) extension. It shapes every session with a system prompt you control, loads the project you're working in, provisions disposable worktrees for parallel work, and dispatches isolated agents you merge like branches.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

## What's in it

- **System prompt** — fully replaced and layered (mode, style, voice, craft, environment, capabilities, project context), overridable per piece
- **Projects & context** — detects the repo you launch in; loads its config, working style, and `AGENTS.md`
- **Worktrees** — planning in the protected checkout; approved work in a labeled worktree so parallel sessions don't collide
- **Agents** — scouts, reviewers, and workers, each in its own workspace; integrated with `git merge`
- **Guardrails** — a bash reviewer on every command, a continuation guard on every stop
- **Review** — `/diff` and `/skill:code-review` for reviewing a branch

## Read more

- [Getting started](getting-started/installation.md) — install and your first session
- [Using basecamp](using/slash-commands.md) — commands, worktrees, diff review, subagents, the dashboard
- [Configuration](configuration/projects.md) — projects, worktree environments, model aliases
- [Architecture](architecture/core.md) — how the prompt, dispatch, worktrees, guardrails, and hub fit together
