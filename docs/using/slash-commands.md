# Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/show-plan` | Show the current plan and task progress |
| `/worktree [label]` | Create a worktree or switch to an existing one (`/worktree prune` reclaims dormant ones) |
| `/skill:pull-request` | Prepare or publish a pull request and carry it through CI |
| `/skill:code-review` | Run an independent multi-agent review of the current branch |
| `/diff [last]` | Review this branch's changes in hunk and send your inline notes back to the agent (`/diff last` reviews only what changed since your last `/diff`) |
| `/title [text]` | Generate a session title from the conversation, or set one manually |
| `/model-aliases` | Manage model aliases (list, add, edit, remove) |

The model-invocable `pull-request` skill is primary-only. New PRs stay draft through CI, and the skill asks before marking one ready; without explicit ready intent it stops at the green draft. It follows repository-required reviews after readiness and never merges the PR.
