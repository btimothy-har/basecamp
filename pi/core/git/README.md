# git

Git mechanics used by the workspace runtime, swarm, and repository-status UI.

## What it does

- **`worktrees/`** — git-worktree mechanics: `crud.ts` (get-or-create · attach · list · records), `target.ts` (path/label resolution), `migrate.ts` (relocate legacy worktrees to the canonical root), and lifecycle cleanup.
- **`repo.ts`** — repo detection: `resolveGitInfo` (repo root, remote, linked-worktree status) and branch helpers.
- **`pr-status.ts`** — read-only pull-request lookup for the repository-status footer.
- **`constants.ts`** — `WORKTREES_ROOT` (`~/.worktrees`) and worktree label/branch conventions.

## Consumers

`#core/git/worktrees/*` and `#core/git/repo.ts` are imported by `core/project/workspace/` and swarm provisioning. The repository-status UI imports `pr-status.ts` directly.
