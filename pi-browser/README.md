# pi-browser

Basecamp browser automation tools for a real headed Chrome/Brave browser over the Chrome DevTools Protocol.

## Tools

- **browser_eval**: runs an async JavaScript function body with a puppeteer `Page` named `page` in scope, so a single call can navigate (`await page.goto(url)`), interact (click/type), and `return` extracted data.
- **browser_screenshot**: captures the current viewport, the full page, or a CSS-selector element and returns both an inline image and a saved scratch file path.

## Browser behavior

- **Driver**: `puppeteer-core` attached over CDP at `http://localhost:9222`; the browser is launched lazily on first use and reused across calls. On session shutdown the connection is disconnected, not killed.
- **Browser resolution**: `BASECAMP_BROWSER_PATH` (explicit executable) → Google Chrome → Brave. Set `BASECAMP_BROWSER_PATH` to target a different Chromium build or platform.
- **Profile**: persistent at `~/.pi/basecamp/browser/profile`, so logins and cookies survive across sessions.
- **Scope**: main session only. Both tools are excluded from subagents and refuse to run when `isSubagent()` is true.

## Installation

```bash
pi install /path/to/pi-browser
```

Installed automatically by `install.py` when the browser component is selected.
