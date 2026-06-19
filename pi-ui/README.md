# pi-ui

Basecamp session UI — status footer, title auto-naming, and interactive mode editor.

## What it does

- **Status footer**: renders worktree label, agent mode, invoked skills, and companion-active indicator as a persistent UI frame
- **Title auto-naming**: generates short session titles from conversation context using a low-cost model
- **Mode editor**: interactive picker for switching between agent modes (analysis/planning/supervisor/executor)
- **Mode styles**: color/label palette mapping for each agent mode

## Dependencies

- **pi-core** (hard peer dep): agent-mode state, workspace state, skill-tracker, model-alias resolution, companion-active flag

The footer reads `isCompanionActive()` from pi-core (a state cell written by pi-companion). If pi-companion isn't installed, the flag stays `false` and the footer omits the companion indicator — no try/catch needed since pi-core is always present.

## Installation

```bash
pi install /path/to/pi-ui
```

Installed automatically by `install.py`.
