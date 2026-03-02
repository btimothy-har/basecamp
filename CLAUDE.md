# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**basecamp** is a Claude Code multi-project workspace launcher. It launches Claude with pre-configured directories, custom prompts, and specialized agents based on project definitions in `~/.basecamp/config.json`.

## Commands

```bash
basecamp setup                           # Initialize environment (prerequisites, dirs, config)

basecamp start <project>                # Start Claude in project directory
basecamp start -r <project>             # Resume a previous conversation
basecamp start -l auth <project>        # Work in worktree "auth" (creates if new, re-enters if exists)

basecamp open <project>                 # Open VS Code with basecamp + project directories
basecamp open -n <project>              # Open in a new VS Code window
basecamp open -l auth <project>         # Open VS Code in existing worktree "auth"

basecamp project list                   # List available projects
basecamp project add                    # Interactively add a new project
basecamp project edit <name>            # Interactively edit a project
basecamp project remove <name>          # Remove a project

basecamp worktree list <project>        # List worktrees for a project
basecamp worktree list --all            # List all worktrees across all repos
basecamp worktree clean <project>       # Interactive worktree cleanup
basecamp worktree clean <project> --all # Remove all worktrees for project
```

> **Note**: Requires installation via `uv tool install -e ./core`. See [README.md](README.md) for details.

## Architecture

### Configuration Flow

```
config.json → ProjectConfig validation → Prompt assembly → Claude CLI execution
```

1. **Project Configuration** (`config.json`): Defines projects with directories and working style
2. **System Prompt Assembly**: Merges environment.md (+ runtime info) → working style → system.md
3. **Plugin Loading**: Discovers agents, skills, commands, hooks from plugin modules
4. **Launch**: Changes to primary directory and `execvp` to claude CLI

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `core/src/core/prompts/` | Package prompts — environment.md, system.md, working_styles/ (shipped defaults) |
| `.claude-plugin/` | Plugin marketplace configuration |
| `~/.worktrees/` | Git worktrees organized by repo name (hidden in home directory) |
| `core/tests/` | pytest test suite for basecamp-core |

**User directory** (`~/.basecamp/`):

| Path | Purpose |
|------|---------|
| `~/.basecamp/config.json` | Workspace settings and project definitions |
| `~/.basecamp/prompts/system.md` | User system prompt override |
| `~/.basecamp/prompts/working_styles/` | User working style overrides or custom styles |
| `~/.basecamp/prompts/context/` | Per-project context files (injected at session start) |

### Git Worktree Integration

Use `-l <label>` to work in an isolated git worktree:

```
~/.worktrees/<repo-name>/<label>/
├── .meta/<label>.json     # Metadata (name, branch, created_at, project, repo_name)
└── <repo contents>        # Working copy on wt/<label> branch
```

| Module | Purpose |
|--------|---------|
| `worktrees.py` | Core worktree operations (create, list, remove, get_or_create) |
| `exceptions.py` | `WorktreeError`, `NotAGitRepoError`, `WorktreeNotFoundError`, `WorktreeCommandError` |
| `constants.py` | `WORKTREES_DIR` path constant |

Key behaviors:
- Worktrees are opt-in via `-l <label>` flag
- Label is both the directory name and worktree identifier
- `basecamp start -l auth` creates or re-enters worktree "auth" with branch `wt/auth`
- `basecamp open -l auth` opens existing worktree (errors if not found)
- Secondary dirs (`--add-dir`) stay on main branch

### Plugin Modules

basecamp includes a bundled core plugin and a marketplace with optional plugins. Each plugin has its own `.claude-plugin/plugin.json`.

**Bundled Plugin** (always loaded):

| Plugin | Directory | Contents |
|--------|-----------|----------|
| `ws-workspace` | `plugins/workspace/` | Project context injection at session start |

**Marketplace Plugins** (optional, installed via `.claude-plugin/marketplace.json`):

| Plugin | Directory | Contents |
|--------|-----------|----------|
| `ws-collab` | `plugins/collaboration/` | Collaborative discovery and planning skills |
| `ws-cursor` | `plugins/cursor/` | Hooks for .cursor context file discovery |
| `ws-eng` | `plugins/engineering/` | Agents, commands, skills, hooks for engineering workflows |
| `ws-gpg-check` | `plugins/gpg_check/` | Pre-tool hook for GPG card verification |

#### ws-collab Plugin Structure

```
plugins/collaboration/
├── .claude-plugin/plugin.json
└── skills/           # discovery (requirements gathering and interviewing)
```

#### ws-eng Plugin Structure

```
plugins/engineering/
├── .claude-plugin/plugin.json
├── agents/           # code-reviewer, code-simplifier, comment-analyzer, etc.
├── commands/         # commit, pullrequest
├── hooks/            # UserPromptSubmit reminders, Write|Edit skill reminder
├── scripts/          # skill-scoped allow hooks for PR workflows
└── skills/           # python-development, sql, pull-request, pr-review, etc.
```

#### ws-workspace Plugin Structure (Bundled)

```
plugins/workspace/
├── .claude-plugin/plugin.json
├── hooks/            # SessionStart hook
└── scripts/          # project-context.sh
```

### Agent Definition Format

```markdown
---
description: When to use this agent
model: opus  # optional
tools: [Read, Grep, Glob]  # optional
---

Agent prompt content here...
```

### Project Configuration Options

```json
{
  "project-name": {
    "dirs": ["path/relative/to/home"],  // First is primary (cwd), rest are --add-dir
    "description": "Project description",
    "working_style": "engineering",  // optional, see working styles below
    "context": "project"  // optional, loads ~/.basecamp/prompts/context/{name}.md
  }
}
```

### Prompt Assembly Order

1. Runtime `<env>` block + `core.prompts/environment.md` + git status (always)
2. Working style prompt (if `working_style` specified) — user override → package default
3. System prompt — user override (`~/.basecamp/prompts/system.md`) → package default
4. Context file (if `context` specified and `~/.basecamp/prompts/context/{name}.md` exists, injected via SessionStart hook)

### Prompt Layer Architecture

| Layer | Location | Purpose |
|-------|----------|---------|
| Environment | `core/src/core/prompts/environment.md` | CLI context, Python/uv, scratch workspace, git status (always loaded) |
| Working Style | `~/.basecamp/prompts/working_styles/` → `core/src/core/prompts/working_styles/` | Project-specific behaviors: work structure, communication, code quality (mutually exclusive) |
| System | `~/.basecamp/prompts/system.md` → `core/src/core/prompts/system.md` | Working principles, task management, skills, tool usage |
| Project Context | `~/.basecamp/prompts/context/` | Per-project context injected at session start (optional) |

### Available Working Styles

Package defaults (in `core/src/core/prompts/working_styles/`):

| File | Purpose |
|------|---------|
| `engineering.md` | Partner role, quest-based work structure, code quality practices, frequent check-ins |
| `advisor.md` | Advisor role, efficient discovery, direct communication, decision support |

Override or add custom styles by placing files in `~/.basecamp/prompts/working_styles/`.

### Built-in Project

The `workspace` project is hardcoded to start with basecamp itself as the working directory.

## Environment Variables

- `BASECAMP_PROJECT`: Set during start to the project name being started
- `BASECAMP_REPO`: Set during start to the git repo directory name (falls back to primary dir name for non-git projects)
- `BASECAMP_CONTEXT_FILE`: Set during start to the resolved context file path (if `context` field is configured and file exists)
