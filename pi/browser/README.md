# browser

Primary-session browser automation through the pinned official Playwright CLI and a Basecamp-owned agent skill.

## Session surface

The browser domain registers no Pi tools. In primary sessions it:

- contributes `skills/playwright-cli/SKILL.md` through `resources_discover`;
- prepends only `pi/browser/bin/` to `PATH`, with duplicate entries removed on reload;
- exposes the `playwright-cli` shim from that private directory.

Subagent sessions receive no browser skill and remove the private directory from `PATH`. The shim also rejects `BASECAMP_AGENT_DEPTH > 0`. This protects the advertised interface; as elsewhere in Basecamp, unrestricted `bash` is not a security sandbox.

## Workflow

Load the `playwright-cli` skill for browser tasks. Its default loop is:

1. `playwright-cli open <url>` or `goto <url>`;
2. inspect the accessibility snapshot;
3. act through stable element refs;
4. snapshot again after state changes.

Use `eval` for a single page or element expression and `run-code` for multi-step Playwright APIs. Screenshots are file-based: run `playwright-cli screenshot` without a relative filename, then inspect the reported PNG with Pi's `read` tool. A relative `--filename` is resolved from the current directory and can dirty the repository.

## Runtime policy

- **Dependency**: `@playwright/cli` is exact-pinned in the root package and lockfile. Version 0.1.17 currently carries a Playwright 1.62 alpha runtime, so upgrades are deliberate. The shim never uses a global install or `npx`, and blocks the CLI's installation commands.
- **Browser**: headed Chrome by default. `PLAYWRIGHT_MCP_EXECUTABLE_PATH` takes precedence, followed by `BASECAMP_BROWSER_PATH`; on macOS the shim then checks Google Chrome and Brave. Other platforms use Playwright's Chrome-channel resolution. The pinned upstream Chromium launcher adds `--disable-blink-features=AutomationControlled`, which causes Chrome's generic unsupported-flag banner; Basecamp does not hide it with another flag.
- **Profile**: `PLAYWRIGHT_MCP_ISOLATED=false` by default, so Playwright creates and owns a fresh persistent profile for its workspace/session. Basecamp does not force a user-data directory.
- **Lifecycle**: the Playwright daemon preserves browser state across CLI commands. `playwright-cli close` stops the current browser session while retaining its managed profile. Basecamp does not kill CLI sessions on Pi shutdown.
- **Artifacts**: the default output directory is `~/.pi/basecamp/browser/playwright-output`, created as `0700`; the shim uses umask `077`, and Playwright removes older artifacts when the directory exceeds 512 MiB. Explicit output overrides should use an absolute non-project path.

The shim defaults `PLAYWRIGHT_MCP_HEADLESS=false`, `PLAYWRIGHT_MCP_ISOLATED=false`, `PLAYWRIGHT_MCP_BROWSER=chrome`, `PLAYWRIGHT_MCP_OUTPUT_DIR`, and `PLAYWRIGHT_MCP_OUTPUT_MAX_SIZE=536870912`. Explicit `PLAYWRIGHT_MCP_*` values win. `BASECAMP_BROWSER_PATH` remains the Basecamp-specific executable override.

## Legacy state

The former Puppeteer profile at `~/.pi/basecamp/browser/profile` is not reused, migrated, chmodded, or deleted by the browser integration, and the integration never attaches to or terminates a legacy Chrome process listening on port 9222. Legacy state is handled separately after its browser is closed: `basecamp doctor --clean` is the one sanctioned path that reclaims the retired profile, and only once it is provably unused (no live `SingletonLock` holder, cold past the staleness threshold) and the user confirms.
