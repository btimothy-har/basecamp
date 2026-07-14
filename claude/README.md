# basecamp-claude

Standalone Claude Code integration for basecamp, delivered as a **Claude Code
plugin**. The plugin bundles native components (skills, hooks, commands)
alongside a **stdio MCP server** that injects each project's related directories
and custom context into the session.

> **Status: design settled, not yet implemented.** This README is the design
> record for the package. Nothing is built yet — it describes the intended
> shape.

## What it is

basecamp-claude is a Claude Code **plugin** — the container — not a CLI wrapper
and not a bare MCP server. It loads through Claude Code's native plugin
mechanisms (`--plugin-dir`, `--plugin-url`, or a marketplace), the faithful
analog of how basecamp loads as a session-scoped extension today, minus the
wrapper that owned the `claude` invocation and replaced the whole system prompt.

Its components map to Claude Code's plugin layout:

| Component | Path | basecamp's use |
| --- | --- | --- |
| MCP server | `.mcp.json` | the dynamic context server (dirs + context; later, orchestration tools) |
| Skills | `skills/` | engineering skills + a `copilot` skill |
| Hooks | `hooks/hooks.json` | `SessionStart` setup; optional `PreToolUse` command guard |
| Commands | `commands/` | basecamp slash commands (new invocable commands are just skills) |
| Agents | `agents/` | custom subagent personas, if any survive the native-CC cut |
| Executables | `bin/` | ships `basecamp-mcp` (and `herdr`) on the Bash `PATH` |
| Manifest | `.claude-plugin/plugin.json` | name/version; namespaces skills as `/basecamp:<name>` |

## The organizing principle: static vs dynamic

Every basecamp capability lands in one of four homes, decided by two questions —
*does Claude Code already do it?* and *is it static or computed per session?*

- **Dynamic** context and actions (which dirs, which project context, live repo
  memory, orchestration) → **the MCP server**, because nothing native injects
  *computed* per-session instructions. This rests on one validated fact: Claude
  Code injects an MCP server's `instructions` field into the system prompt at
  session start, capped at 2KB and truncated (official MCP reference; injection
  confirmed via `anthropics/claude-code#30135`).
- **Static** assets (skills, hooks, commands, agents) → **native plugin
  components**, which have first-class homes and shouldn't be contorted into MCP.
- **Permissions** → **external** (the user's `~/.claude/settings.json`, or
  written once by `basecamp setup`). The plugin cannot ship them: plugin
  `settings.json` supports only the `agent` and `subagentStatusLine` keys.
- **Already native to Claude Code** → **dropped**.

## Full inventory

### → MCP server — context (resources + the `instructions` router)

| Capability | Surface | Tier |
| --- | --- | --- |
| Related project directories (awareness) | `instructions` field (2KB) + `basecamp://project/dirs` | 0 |
| Project custom context (named context file, AGENTS.md/CLAUDE.md) | `basecamp://project/context` | 0 |
| Logseq repo memory (repo cockpit, work dossiers) | `basecamp://logseq/repo`, `basecamp://logseq/dossier/<slug>` (read) | 1 |

All resolved from the `projects` section of `~/.pi/basecamp/config.json` — the
same resolution `pi/core/project/config.ts` performs today, so basecamp config
stays the single source of truth for a project's `additionalDirs` and context.

### → MCP server — orchestration tools (Tier 2, local stdio only)

| Capability | Surface | Note |
| --- | --- | --- |
| Worktree lifecycle (create / switch) | tools | opinionated `~/.worktrees/<org>/<name>/<label>` layout CC lacks |
| Workstreams (create / edit / launch / list / status) | tools + list resource | daemon-backed (SQLite store) |
| Cross-session agent messaging (`ask_agent`, `message_agent`) | tools | basecamp's differentiator over CC's within-session subagents |
| Herdr pane launching | tool (shell-out) or `monitors/` status push | host tmux only; no-ops in web sessions |
| Logseq memory curation (append) | tools | the write side of the Tier-1 read resources |
| BigQuery `bq_query` | tool (optional) | project-specific; or a dedicated BigQuery MCP |

Tier 2 turns the server from *awareness* into *orchestration* — a deliberate
scope jump. Because these tools shell out to the host, they work only in local
stdio sessions.

### → Native plugin components (static)

| Capability | Home |
| --- | --- |
| Skills: `sql`, `data-warehousing`, `python-development`, `marimo`, `data-analysis`, `planning`, `gather`, `agents` | `skills/` — port existing `SKILL.md` files verbatim |
| Copilot posture (was a session mode) | a new `copilot` skill in `skills/` |
| Per-repo session setup (was the worktree setup hook) | `hooks/hooks.json` → `SessionStart` |
| Bash/git command triage (`bash-reviewer`) | `hooks/hooks.json` → `PreToolUse`, *only if wanted* — see Dropped |
| basecamp slash commands | `commands/` (or `skills/`) |

### → External (not shippable by the plugin)

| Capability | Home |
| --- | --- |
| Cross-repo read boundary (`Read(~/code/**)` allow rule + secret `deny`s) | user's `~/.claude/settings.json`, or written once by `basecamp setup` |

### → Dropped — Claude Code already provides it

| basecamp capability | Native Claude Code equivalent |
| --- | --- |
| `dispatch_agent` / within-session subagents | native subagents + `agents/` |
| `plan()` / plan mode | native plan mode |
| Task tracking (`create_tasks`, `start_task`, …) | native todos |
| `escalate` | native ask-user |
| Nested AGENTS.md / CLAUDE.md injection | native hierarchical `CLAUDE.md` loading (cwd + parents) |
| `/code-review` + `report_findings` | native `/review` + `security-review` skill |
| `bash-reviewer` as an always-on reviewer | `auto` mode's background safety checks — and MCP can't intercept the host `Bash` tool regardless |
| Model aliases (`/model-aliases`) | native `/model` |
| Workspace guards (protected checkout, `allowed_dirs`) | native permission rules + sandbox |
| Browser (`browser_eval`, `browser_screenshot`) | an existing Playwright / Puppeteer MCP |
| analysis / planning / work session modes | plan mode + default posture (postures don't port as *enforced* modes) |

## Tiers

- **Tier 0 — the awareness MVP:** dirs + context resources. Zero tools. Complete
  and shippable on its own.
- **Tier 1 — still pure awareness:** add the Logseq repo-memory resources
  (read-only).
- **Tier 2 — orchestration tool layer (local only):** worktrees, workstreams,
  cross-session messaging, Herdr, BigQuery. A real product decision — build it
  only to have the agent *do* basecamp orchestration, not just be *aware* of
  context.
- **Native track (parallel, not MCP):** port the engineering skills, add the
  `copilot` skill, wire the `SessionStart` setup hook.

## Load-bearing constraints

- **`instructions` is 2KB, truncated.** It is a router (project identity + dir
  list + pointer to the context resource), never the payload; bulk lives in
  resources.
- **MCP servers cannot intercept the host's native tools.** Command gating is
  Claude Code's permission layer — so `bash-reviewer` can only ever be a
  `PreToolUse` hook, never an MCP feature.
- **Plugin `settings.json` supports only `agent` and `subagentStatusLine`.** The
  plugin cannot grant the read boundary; permissions stay external.
- **Tier-2 host tools are local-stdio only.** In Claude Code on the web the
  server runs in the web sandbox with no host tmux or daemon, so worktree and
  Herdr tools no-op there.
- **Plan-mode caveat.** Claude Code's own plan mode reportedly ignores `Read`
  allow rules for files outside the project dir (`anthropics/claude-code#23759`);
  it bites only when the user is literally in shift-tab plan mode.

## Model-facing content principle

The text the server injects — the `instructions` field and resource bodies —
must read as clean, native project guidance: project facts and pointers, not
basecamp/Pi runtime jargon, and never Pi-only runtime behavior. The MCP client
already labels the source as the `basecamp` server, so the injected text stays
about the project, not about the tool delivering it.
