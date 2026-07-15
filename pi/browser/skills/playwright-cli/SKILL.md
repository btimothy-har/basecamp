---
name: playwright-cli
description: Automate a real headed browser with Playwright CLI. Use for browsing, interacting with pages, visual inspection, web research, UI testing, or browser debugging.
allowed-tools: Bash(playwright-cli:*) Read
---

# Playwright CLI

Use Basecamp's `playwright-cli` command. It is pinned, configured, and restricted to the primary session.

Never use `npx`, install a global CLI or browser, invoke `node_modules/.bin` directly, or bypass the Basecamp command. Use `playwright-cli --help [command]` when the concise workflow below is insufficient.

## Interaction loop

1. Open or navigate to the page.
2. Inspect the accessibility snapshot.
3. Act on a stable element ref such as `e15`.
4. Snapshot again after navigation or meaningful state changes.

```bash
playwright-cli open https://example.com
playwright-cli snapshot
playwright-cli click e15
playwright-cli fill e22 "value" --submit
playwright-cli snapshot
```

Prefer snapshot refs over CSS selectors. Use `playwright-cli find "text"` to search a large snapshot. Direct commands such as `click`, `fill`, `select`, `check`, `press`, and `upload` are clearer and safer than arbitrary code.

## Evaluation and Playwright code

Use `eval` for a single page expression or a function applied to one referenced element.

```bash
playwright-cli eval "document.title"
playwright-cli eval "el => el.textContent" e15
```

Use `run-code` when the task needs Playwright APIs, multiple steps, or structured extraction. The argument is an async function receiving `page`.

```bash
playwright-cli run-code "async page => await page.getByRole('main').innerText()"
```

Do not use `eval` or `run-code` when a dedicated CLI command expresses the action.

## Screenshots

Snapshots are the default inspection method. When pixels matter, save a screenshot and then inspect the reported PNG path with Pi's `read` tool.

```bash
playwright-cli screenshot --filename=page.png
playwright-cli screenshot e15 --filename=element.png
```

Browser artifacts are routed outside the project checkout. Do not redirect snapshots or screenshots into the repository unless the user explicitly requests a project artifact.

## Tabs and lifecycle

```bash
playwright-cli tab-list
playwright-cli tab-new https://example.com/other
playwright-cli tab-select 0
playwright-cli tab-close 1
playwright-cli close
```

The default profile is persistent, so cookies and local storage survive `close` and later sessions. Use a named session only when parallel independent browsers are necessary: pass `-s=<name>` to every command in that workflow. Do not run `delete-data`, `close-all`, or `kill-all` unless the user explicitly asks to clear or terminate sessions.

For an externally attached browser, use `detach` rather than `close`. Use `playwright-cli --help` for network inspection, console messages, traces, storage, PDFs, video, and the annotation dashboard.
