# git

Git mechanics used by the workspace runtime, swarm, and repository-status UI.

## What it does

- **`worktrees/`** — git-worktree mechanics: `crud.ts` (get-or-create · attach · list · records), `target.ts` (path/label resolution), `migrate.ts` (relocate legacy worktrees to the canonical root, then `rmdir` the emptied legacy root), `lifecycle.ts` (lock/unlock/remove/branch-delete primitives + agent-worktree creation), `lease.ts` (session-worktree advisory leases `basecamp session <sessionId> <ts>` + the clean/dirty teardown matrix), and `session-sweep.ts` (the session-tier cold+clean backstop). The agent-tier backstop sweep lives in the Python daemon (`src/basecamp/hub/swarm/sweep.py`), not here.
- **`constants.ts`** — `worktreesRoot()` resolves the root at use-time (`BASECAMP_WORKTREES_ROOT` override, default `~/.worktrees`) plus label/branch conventions.
- **`repo.ts`** — repo detection: `resolveGitInfo` (repo root, remote, linked-worktree status) and branch helpers.
- **`pr-status.ts`** — read-only pull-request lookup for the repository-status footer.

## Consumers

`#core/git/worktrees/*` and `#core/git/repo.ts` are imported by `core/project/workspace/` and swarm provisioning. The repository-status UI imports `pr-status.ts` directly.
