# Git Worktrees

A worktree is a separate working directory for a git branch. basecamp uses them so parallel sessions never fight over your checkout: implementation work happens in its own worktree, and the repository's main checkout stays untouched.

## How they activate

When you launch Pi, you start in the repository's protected checkout (its main directory), with no worktree active. When you approve an implementation plan, basecamp offers an execution worktree, suggests a label from the plan goal, and switches you into it. You can also create or switch worktrees any time with [`/worktree`](slash-commands.md).

Before activation the protected checkout must be on the default branch. A dirty checkout doesn't block activation: worktrees are cut from HEAD, and any uncommitted changes in the checkout stay where they are.

## Where they live

Worktrees are stored under `~/.worktrees/<org>/<name>/<label>/`. The directory label is deliberately generic (`wt/<slug>`, or `copilot/<slug>` for workstreams) because the worktree is disposable; the branch it holds is the durable identity of the work. Git is the source of truth for which worktrees exist, and basecamp keeps no separate registry.

## Working in a worktree

Once a worktree is active:

- Implementation edits happen in the worktree, not the protected checkout.
- Relative file paths target the worktree (your launch subdirectory is preserved where applicable).
- Mutating `git` and `gh` commands run through the bash reviewer, and edits or git operations are blocked unless your working directory is inside the active worktree.
- Resumed, reloaded, or forked sessions restore their last worktree when still in the same repo.

Additional directories configured for a project stay on their own checkouts throughout. Worktrees apply only to git repositories.

## Managing worktrees

Worktrees stay human-managed. Inside Pi, use `/worktree` to create one, switch between live ones, or `/worktree prune` to reclaim dormant ones. Outside Pi, use native git: `git worktree list` to inspect, `git worktree remove` to clean up.

For the full lifecycle, lease protocol, and teardown rules, see [Worktree Lifecycle & Teardown](../architecture/worktree-lifecycle.md).
