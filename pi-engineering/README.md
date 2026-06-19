# pi-engineering

Basecamp engineering tools and skills — BigQuery, Python, SQL, dbt, marimo, code review.

## What it does

- **bq_query tool**: BigQuery SQL execution from `.sql` files under the workspace scratch directory
- **Engineering skills**: Python development, SQL, data warehousing (dbt), marimo notebooks, data analysis, code review, pi development
- **Engineering prompts**: domain-specific prompt templates

## Dependencies

- **pi-core** (hard peer dep): workspace effective cwd, workspace state (scratch dir)

## Installation

```bash
pi install /path/to/pi-engineering
```

Installed automatically by `install.py`.
