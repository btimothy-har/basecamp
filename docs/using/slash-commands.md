# Slash Commands

| Command | Description |
|---------|-------------|
| `/show-plan` | Show the current plan and task progress |
| `/worktree [label]` | Create a worktree or switch to an existing one (`/worktree prune` reclaims dormant ones) |
| `/diff [last]` | Review this branch's changes in hunk and send your inline notes back to the agent (`/diff last` reviews only what changed since your last `/diff`) |
| `/title [text]` | Generate a session title from the conversation, or set one manually |
| `/model-aliases` | Manage model aliases (list, add, edit, remove) |
| `/pull-request [additional instructions]` | Prepare or publish a pull request and carry it through CI |
| `/code-review [additional instructions]` | Run an independent multi-agent review of the current branch |

`/pull-request` and `/code-review` are thin primary-only prompt commands. Each unconditionally directs the agent to load and apply its matching model-invocable skill, with any arguments passed as additional instructions; the skills remain the authoritative guidance.
