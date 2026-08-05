# Skills

basecamp comes bundled with several built-in skills — scoped capabilities with their own guidance. The agent loads them as the work calls for them, and you can also invoke any directly with `/skill:<name>`.

## User and Agent Invoked

The agent loads these as needed; you can also invoke any with `/skill:<name>`.

| Skill | What it does |
|-------|--------------|
| `pull-request` | Prepare, publish, and carry a pull request through CI — opens as draft, asks before marking ready, never merges |
| `agents` | Delegate bounded work to agents |
| `gather` | Requirements gathering |
| `planning` | Planning |
| `frontend-design` | Building interfaces |
| `playwright-cli` | Browser automation |
| `data-analysis` | Data analysis and research |
| `data-warehousing` | Warehouse modeling (dbt) |
| `sql` | SQL queries and schema |
| `python-development` | Python guidance |
| `pi-development` | Pi extension, skill, and theme authoring |
| `marimo` | Marimo reactive notebooks |
| `copilot` | Repo-memory curation (copilot mode) |

## User-Invoked Skills

The agent can't load these on its own — you trigger them with `/skill:<name>`.

| Skill | What it does |
|-------|--------------|
| `code-review` | An independent multi-agent review of the current branch — dispatches reviewer specialists; you synthesize their reports and a verdict is computed over the final set |
