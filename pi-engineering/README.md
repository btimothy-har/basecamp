# pi-engineering

Basecamp engineering tools and skills — BigQuery, Python, SQL, dbt, marimo, code review.

## What it does

- **bq_query tool**: BigQuery SQL execution from `.sql` files under the workspace scratch directory
- **browser_eval / browser_screenshot tools**: drive a real headed Chrome/Brave over the Chrome DevTools Protocol
- **Engineering skills**: Python development, SQL, data warehousing (dbt), marimo notebooks, data analysis, code review, pi development
- **Engineering prompts**: domain-specific prompt templates

## Browser tools

`browser_eval` runs an async JavaScript function body with a puppeteer `Page` named `page` in scope, so a single call can navigate (`await page.goto(url)`), interact (click/type), and `return` extracted data. `browser_screenshot` captures the current viewport, the full page, or a CSS-selector element.

- **Driver**: `puppeteer-core` attached over CDP at `http://localhost:9222`; the browser is launched lazily on first use and reused across calls. On session shutdown the connection is disconnected, not killed.
- **Browser resolution**: `BASECAMP_BROWSER_PATH` (explicit executable) → Google Chrome → Brave. Set `BASECAMP_BROWSER_PATH` to target a different Chromium build or platform.
- **Profile**: persistent at `~/.pi/basecamp/browser/profile`, so logins and cookies survive across sessions.
- **Scope**: main session only. Both tools are excluded from subagents and refuse to run when `isSubagent()` is true.

## Dependencies

- **pi-core** (hard peer dep): workspace effective cwd, workspace state (scratch dir), env contract, basecamp paths
- **puppeteer-core**: CDP driver for the browser tools (no bundled browser download)

## Installation

```bash
pi install /path/to/pi-engineering
```

Installed automatically by `install.py`.
