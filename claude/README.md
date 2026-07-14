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

One row per basecamp capability: whether Claude Code already covers it, and
where it lands. The MCP-context rows resolve from the `projects` section of
`~/.pi/basecamp/config.json` — the same resolution `pi/core/project/config.ts`
performs today, so basecamp config stays the single source of truth.

| Capability | Claude Code native? | Home / verdict |
| --- | --- | --- |
| Related project directories (awareness) | ❌ no dynamic-instruction channel | **MCP** — `instructions` + `basecamp://project/dirs` · Tier 0 |
| Project custom context (context file, AGENTS.md/CLAUDE.md) | ❌ | **MCP** — `basecamp://project/context` · Tier 0 |
| Logseq repo memory (cockpit, dossiers) | ❌ no analog | **MCP resource** (read) · Tier 1 |
| Worktree lifecycle (create / switch) | ⚠️ raw git worktrees, not this lifecycle | **MCP tool** · Tier 2, local-only |
| Workstreams (create / edit / launch / list / status) | ❌ no analog | **MCP tools + resource** · Tier 2, daemon-backed |
| Cross-session agent messaging (`ask_agent`, `message_agent`) | ⚠️ subagents are within-session only | **MCP tools** · Tier 2 |
| Herdr pane launching | ❌ no analog | **MCP tool** (shell-out) or `monitors/` · Tier 2, local-only |
| Logseq memory curation (append) | ❌ | **MCP tools** · Tier 2 |
| BigQuery `bq_query` | ❌ | **MCP tool** (optional), or a dedicated BigQuery MCP |
| Skills: `sql`, `data-warehousing`, `python-development`, `marimo`, `data-analysis`, `planning`, `gather`, `agents` | ✅ skills | **Native** — `skills/` (port `SKILL.md` verbatim) |
| Session-mode postures (analysis / planning / work / copilot) | ⚠️ don't port as *enforced* modes | **Native** — posture skills in `skills/` |
| Per-repo session setup (was the worktree setup hook) | ✅ hooks | **Native** — `hooks/hooks.json` → `SessionStart` |
| `bash-reviewer` | ✅ `auto` mode; and MCP can't intercept host `Bash` | **Native hook** if wanted (`PreToolUse`); else drop |
| basecamp slash commands | ✅ commands / skills | **Native** — `commands/` |
| Cross-repo read boundary (`Read(~/code/**)` + secret `deny`s) | ✅ settings | **External** — user settings, or `basecamp setup` |
| `dispatch_agent` / within-session subagents | ✅ subagents + `agents/` | **Drop** |
| `plan()` / plan mode | ✅ plan mode | **Drop** |
| Task tracking (`create_tasks`, `start_task`, …) | ✅ todos | **Drop** |
| `escalate` | ✅ ask-user | **Drop** |
| Nested AGENTS.md / CLAUDE.md injection | ✅ hierarchical `CLAUDE.md` (cwd + parents) | **Drop** |
| `/code-review` + `report_findings` | ✅ `/review` + `security-review` skill | **Drop** |
| Model aliases (`/model-aliases`) | ✅ `/model` | **Drop** |
| Workspace guards (protected checkout, `allowed_dirs`) | ✅ permissions + sandbox | **Drop** |
| Browser (`browser_eval`, `browser_screenshot`) | ⚠️ Playwright MCP exists | **Drop** — use an existing browser MCP |

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
