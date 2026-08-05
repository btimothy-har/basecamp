# Skills

basecamp comes bundled with several built-in skills — scoped capabilities with their own guidance. The agent loads them as the work calls for them, and you can also invoke any directly with `/skill:<name>`.

## User-invoked only

The agent can't load these on its own — you trigger them with `/skill:<name>`.

- **`code-review`** — an independent multi-agent review of the current branch. Dispatches reviewer specialists; you synthesize their reports and a verdict is computed over the final set.

## User and agent invoked

The agent loads these as needed; you can also invoke any with `/skill:<name>`.

- **`pull-request`** — prepare, publish, and carry a PR through CI (opens as draft, asks before ready, never merges)
- **`agents`** — delegate bounded work to agents
- **`gather`** — requirements gathering
- **`planning`** — planning
- **`frontend-design`** — building interfaces
- **`playwright-cli`** — browser automation
- **`data-analysis`**, **`data-warehousing`**, **`sql`** — data work and warehouse modeling
- **`python-development`**, **`pi-development`**, **`marimo`** — language and tooling guidance
- **`copilot`** — repo-memory curation (copilot mode)
