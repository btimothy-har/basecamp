# pi-workspace

Basecamp workspace config + project context layer. Overrides pi-core's git-detected workspace defaults with basecamp.yaml-aware values.

## What it does

- **Workspace config**: loads `basecamp.yaml`, manages allowed-roots providers, unsafe-edit flag handling
- **Projects**: assembles the layered system prompt (environment → working style → project context → tools/skills), context injection on every prompt cycle, header rendering
- **WorkspaceService override**: registers a config-aware WorkspaceService into pi-core's workspace registry, replacing pi-core's default. Sets `BASECAMP_*` env vars via pi-core's env contract. Registers cwd provider via pi-core's exec seam.
- **Workspace guards**: blocks writes to critical root-branch paths, warns of unsaved session states
- **Worktree command**: `/worktree` command for switching between git worktrees (primary sessions only)

## Dependencies

- **pi-core** (hard peer dep): workspace registry, exec, env contract, state persistence, worktree git primitives

## Installation

```bash
pi install /path/to/workspace/pi
```

Installed automatically by `install.py`.
