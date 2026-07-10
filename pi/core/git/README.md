# git

Git mechanics + the git command surface. A `pi/core/git/` subsystem — the worktree/repo plumbing is imported directly by the project's workspace runtime and by swarm; the `/create-pr` command is registered by `registerCore` (via `registerGit`).

## What it does

- **`worktrees/`** — the git-worktree mechanics: `crud.ts` (get-or-create · attach · list · records), `target.ts` (path/label resolution), `migrate.ts` (relocate legacy worktrees to the canonical root).
- **`repo.ts`** — repo detection: `resolveGitInfo` (repo root, remote, linked-worktree status) + branch helpers.
- **`constants.ts`** — `WORKTREES_ROOT` (`~/.worktrees`) + the worktree label/branch conventions.
- **`pr.ts` / `index.ts`** — the `/create-pr` command: prompts the agent to create or update a PR via bash/`gh` (checks for an existing PR, pushes the branch if needed, summarizes the result).

## Consumers

`#core/git/worktrees/*` and `#core/git/repo.ts` are imported by `core/project/workspace/` (the worktree runtime) and by `swarm` (workstream provisioning). Everything here imports only `#core/host/exec.ts`.
