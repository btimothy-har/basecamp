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
playwright-cli screenshot
playwright-cli screenshot e15
```

Let Playwright choose the output filename so the shim routes it outside the project checkout. A relative `--filename` writes into the current directory; use one only when the user explicitly requests a project artifact.

## Standalone HTML previews

Use an existing application's own development server and live-reload pipeline. For a focused, self-contained HTML prototype, direct `file:` navigation is blocked; serve the file through a mocked response at an isolated HTTP origin instead. Use a distinct reserved `.test` hostname for each prototype, never a real service domain: the persistent profile retains storage by origin. The commands below use `prototype.test` as a placeholder. Do not register a service worker for a disposable preview.

Read the file first, then open a browser session before installing the route. Substitute the prototype's absolute path and chosen hostname:

```bash
playwright-cli open about:blank
playwright-cli route "http://prototype.test/" --content-type="text/html; charset=utf-8" --body="$(cat "/absolute/path/to/prototype.html")"
playwright-cli goto "http://prototype.test/"
playwright-cli snapshot
```

The route captures the file content at command time. After editing the file, replace the route before reloading:

```bash
playwright-cli unroute "http://prototype.test/"
playwright-cli route "http://prototype.test/" --content-type="text/html; charset=utf-8" --body="$(cat "/absolute/path/to/prototype.html")"
playwright-cli reload
```

Only the document URL is mocked. Keep scripts, styles, and required assets inline; any other request is evidence that the artifact is not self-contained. If the prototype needs application routing, a build pipeline, many files, or a large inline payload, use the project's normal development server instead. Remove the route with `unroute` when the preview is finished.

## Responsive, runtime, and human review

Choose viewports from the product's requirements. At minimum, inspect representative mobile and desktop widths and any point where the layout changes materially.

```bash
playwright-cli resize 390 844
playwright-cli snapshot
playwright-cli screenshot
playwright-cli resize 1440 900
playwright-cli snapshot
playwright-cli screenshot
```

Read each reported screenshot path with Pi's `read` tool. Exercise important states at the relevant size rather than judging only the initial page.

Inspect browser failures after exercising the primary flow:

```bash
playwright-cli console
playwright-cli requests
```

Use `playwright-cli request <index>` when an unexpected request needs details. For live design feedback, run `playwright-cli show --annotate`; the user can mark the rendered page and attach notes for the next iteration.

## Tabs and lifecycle

```bash
playwright-cli tab-list
playwright-cli tab-new https://example.com/other
playwright-cli tab-select 0
playwright-cli tab-close 1
playwright-cli close
```

The default profile is persistent, so cookies and local storage survive `close` and later sessions. Use a named session only when parallel independent browsers are necessary: pass `-s=<name>` to every command in that workflow. Do not run `delete-data`, `close-all`, or `kill-all` unless the user explicitly asks to clear or terminate sessions.

For an externally attached browser, use `detach` rather than `close`. Use `playwright-cli --help` for traces, storage, PDFs, video, and other commands not covered above.
