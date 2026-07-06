# basecamp-claude

Standalone Claude Code launcher for basecamp.

> **Status: planned.** This directory is a placeholder for the package. Nothing
> is implemented yet — this README describes the intended shape.

## Intent

The counterpart to the [Codex projection](../codex/README.md), but for Claude
Code. Where the Codex projection must pre-install assets into `~/.codex` (Codex
cannot be wrapped), this package will own the launch and inject basecamp's
context at launch time — nothing installed into `~/.claude`.

Planned approach:

- A `basecamp-claude` launcher that detects the project and execs `claude` with
  basecamp's replaced system prompt (`--system-prompt-file`) and an extension
  bundle loaded via `--plugin-dir` (skills, agents, hooks) — the faithful analog
  of how basecamp loads as a session-scoped extension today.
- Project detection, worktree handling, and `.env` / `BASECAMP_*` settings
  injection, adapted from basecamp's pre-Pi Claude Code launcher.

Model-facing content added here later must read as native Claude Code guidance
and must not reference basecamp, Pi, or Pi-only runtime behavior.
