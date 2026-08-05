# Skills

basecamp comes bundled with several built-in skills — scoped capabilities with their own guidance that the agent loads as the work calls for them.

## User-invoked skills

Two skills you invoke yourself with `/skill:<name>`. They're hidden from the agent — it can't load them on its own.

| Command | Description |
|---------|-------------|
| `/skill:pull-request` | Prepare or publish a pull request and carry it through CI |
| `/skill:code-review` | Run an independent multi-agent review of the current branch |

Both are primary-only. `/skill:pull-request` opens every PR as a draft and drives it through CI — it asks before marking one ready and never merges on its own. `/skill:code-review` dispatches reviewer specialists, you synthesize their reports, and a verdict is computed over the final set.
