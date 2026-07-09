# ui

Basecamp session UI — status footer, title auto-naming, and interactive mode editor.

## What it does

- **Status footer**: renders cwd, worktree label, branch, agent mode, invoked skills, context usage, and extension statuses as a persistent UI frame
- **Title auto-naming**: generates short session titles from conversation context using a low-cost model
- **Mode editor**: interactive picker for switching between agent modes (analysis/planning/supervisor/executor)
- **Mode styles**: color/label palette mapping for each agent mode

## Dependencies

- **core** (`#core/*`): agent-mode state, workspace state, skill-tracker, and model-alias resolution
