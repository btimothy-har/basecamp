# Worktree environments

A fresh worktree contains tracked files only — gitignored artifacts (`.venv`, `node_modules`, `.env`, build output) are absent. To provision newly created worktrees, configure a per-repo **environment**: a setup command keyed by repo name.

```bash
basecamp environments                       # interactive menu (list / add / edit / remove)
basecamp environments list
basecamp environments set <org>/<name> "uv sync && npm ci"
basecamp environments remove <org>/<name>
```

Environments are stored under the `environments` section of `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename) — i.e. `BASECAMP_REPO`:

```json
{ "environments": { "acme/basecamp": { "setup": "uv sync && npm ci" } } }
```

basecamp ships no default — a repo with no environment is a clean no-op. When an approved implementation plan **creates** a new execution worktree, basecamp resolves the current repo's setup command and runs it before handoff:

- Executed as `bash -lc "<command>"` with the working directory set to the new worktree.
- Inherits the `BASECAMP_*` env vars plus `BASECAMP_REPO_ROOT` (the protected checkout path), so the command can copy or symlink artifacts from the source checkout if it chooses. basecamp does not prescribe what the command does.
- **Blocks** activation with a **180-second timeout**; the fresh session starts only once setup finishes.
- **Warn-and-proceed**: a non-zero exit or timeout surfaces a warning and is recorded in the handoff result, but activation and handoff still complete.
- **Creation only**: it does not run when resuming/attaching an existing worktree or switching via `/worktree`.

For anything beyond a one-liner, point the command at a script you maintain outside the repo, e.g. `"bash ~/.pi/basecamp/worktree-setup.sh"`.
