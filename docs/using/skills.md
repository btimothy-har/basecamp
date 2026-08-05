# Skills

Skills are scoped capabilities with their own deep guidance. Some you invoke yourself; the rest the agent loads on its own when the work calls for them.

## User-invoked skills

You call these with `/skill:<name>`. They're hidden from the agent — it can't load them on its own.

| Command | Description |
|---------|-------------|
| `/skill:pull-request` | Prepare or publish a pull request and carry it through CI |
| `/skill:code-review` | Run an independent multi-agent review of the current branch |

Both are primary-only.

`/skill:pull-request` opens every PR as a draft and drives it through CI; it asks before marking one ready and never merges on its own. `/skill:code-review` dispatches reviewer specialists, you synthesize their reports, and a verdict is computed over the final set.

## Model-invocable skills

The agent loads these based on the task — you don't invoke them directly:

- **frontend-design** — building distinctive, usable interfaces
- **browser automation** — driving a real browser for inspection and testing
- **data-analysis**, **data-warehousing**, **sql** — data work and warehouse modeling
- **python-development**, **pi-development**, **marimo** — language and tooling guidance

It also draws on internal skills — **gather**, **planning**, **agents** — for discovery, planning, and dispatch.
