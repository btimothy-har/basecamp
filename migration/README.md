# Basecamp Extension Migration

Consolidates all pi plugins (`pi-eng`, `pi-git-protect`, `pi-collab`) and the Claude Code `companion` plugin into a single pi extension package at `extension/`.

## Migration Order

Execute these in order — each builds on the previous:

| # | Prompt | What it does | Depends on |
|---|--------|-------------|------------|
| 1 | `01-scaffold.md` | Create `extension/` directory structure, package.json, entry point | — |
| 2 | `02-git-protect.md` | Port git-protect extension (pure TypeScript, no deps) | 1 |
| 3 | `03-lifecycle.md` | Port session lifecycle: env setup, scratch dirs, project context | 1 |
| 4 | `04-observer.md` | Port observer integration: ingest triggers on compact/shutdown/dispatch | 1, 3 |
| 5 | `05-messaging.md` | Port inter-agent inbox: message delivery and consumption | 1, 3 |
| 6 | `06-workers.md` | Port worker lifecycle: close-on-exit | 1, 3 |
| 7 | `07-nudges.md` | Port skill nudging on file edits | 1 |
| 8 | `08-skills.md` | Move all skills into `extension/skills/` | 1 |
| 9 | `09-launch-integration.md` | Update `core/` launch to pass extension to pi instead of companion plugin | 1–8 |
| 10 | `10-cleanup.md` | Delete old plugins, update docs, verify | 1–9 |

## Principles

- Each prompt is self-contained: includes full context, file locations, and acceptance criteria
- The extension is passed to pi via `basecamp launch`, not installed globally
- Skills and prompt templates are bundled in the package via `pi.skills` / `pi.prompts` in package.json
- All companion shell scripts become typed TypeScript event handlers
- `plugins/cursor/` and `plugins/private/` are deleted (not migrated)
- **Migrate as-is first** — env vars, worker operations, and handoff all keep their current shape. The extension reads `process.env.BASECAMP_*` just like the shell scripts did. Simplifying the env var chain (moving state into the extension, removing `build_session_settings`, etc.) is a follow-up tracked in `11-future.md`.
