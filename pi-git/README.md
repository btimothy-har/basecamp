# pi-git

Basecamp git review workflows — code-walkthrough, review_packet, and prompt-only create-pr.

## What it does

- **`/code-walkthrough` command**: starts a context-first code walkthrough for a PR number, branch, or the current branch. PR and branch targets can be opened in dedicated review worktrees before handing the walkthrough prompt to the agent.
- **`review_packet` tool**: opens an interactive review packet walkthrough for the user and returns consolidated, structured feedback to the agent. Review packet artifacts are written under the session scratch directory.
- **`/create-pr` command**: sends a prompt instructing the agent to create or update the PR directly with bash/`gh` commands, including pushing the branch if needed and summarizing the result.
- **Git skill**: `code-walkthrough` workflow guidance.

## Dependencies

- **pi-core** (hard peer dep): exec wrapper, workspace state, worktree operations, and scratch directory context.

## Installation

```bash
pi install /path/to/pi-git
```

Installed automatically by `install.py`.
