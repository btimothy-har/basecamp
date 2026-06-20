# pi-git

Basecamp git workflow — safe-git, status, PR/issue/review-packet commands, publish guard.

## What it does

- **Safe-git tool**: guarded git command execution through an approval blocklist
- **Git commands**: `/create-pr`, `/create-issue`, `/pr-comments`, `/code-walkthrough` — review workflows with automatic worktree switching
- **Status tool**: `git_status` — current repository state summary
- **Publish skill guard**: blocks pushes/PRs unless review validation has passed
- **Review packet**: interactive review packet walkthrough for branches/PRs
- **Git skills**: `pull-request`, `issue-logging` workflow skills

## Dependencies

- **pi-core** (hard peer dep): exec wrapper, workspace state, worktree operations, skill-tracker

## Installation

```bash
pi install /path/to/pi-git
```

Installed automatically by `install.py`.
