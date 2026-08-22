# Worktree Environments

A fresh worktree contains tracked files only; gitignored artifacts (`.venv`, `node_modules`, `.env`, build output) are absent. To provision newly created worktrees, configure a per-repo **environment**: a setup command keyed by repo name.

```bash
basecamp environments                       # interactive menu (list / add / edit / remove)
basecamp environments list
basecamp environments set <org>/<name> "uv sync && npm ci"
basecamp environments remove <org>/<name>
```

Environments are stored under the `environments` section of `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename), i.e. `BASECAMP_REPO`:

```json
{ "environments": { "acme/basecamp": { "setup": "uv sync && npm ci" } } }
```

basecamp ships no default; a repo with no environment is a clean no-op.

Whenever a worktree is created, basecamp runs the repo's setup command once before the session proceeds. It runs as `bash -lc "<command>"` from the new worktree, with the `BASECAMP_*` environment and `BASECAMP_REPO_ROOT` (the protected checkout path) available, so it can copy or symlink artifacts like `.venv` or `node_modules` from the source checkout. basecamp doesn't prescribe what the command does.

Setup is bounded and best-effort: a 3-minute timeout, and on a timeout or non-zero exit the failure is recorded but basecamp continues; the worktree activates and the session starts regardless. It only runs on creation, never on resume, attach, or switch.

For anything beyond a one-liner, point the command at a script you keep outside the repo, e.g. `"bash ~/.pi/basecamp/worktree-setup.sh"`.
