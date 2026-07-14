# basecamp-claude

Standalone Claude Code integration for basecamp, delivered as a **stdio MCP
server** that makes a Claude Code session aware of a project's related
directories and serves its custom context.

> **Status: design settled, not yet implemented.** This README is the design
> record for the package. Nothing is built yet — it describes the intended
> shape.

## What it is

A stdio MCP server, registered per-repo through a project-scope `.mcp.json`
checked into the repository:

```json
{
  "mcpServers": {
    "basecamp": { "type": "stdio", "command": "basecamp-mcp", "args": ["serve"] }
  }
}
```

It is a **guest inside a normal `claude` session**, not a launcher. The user
starts Claude Code however they like — CLI, IDE, or Claude Code on the web, all
of which read `.mcp.json` — and the server attaches and contributes context.
This replaces the earlier CLI-wrapper intent (a `basecamp-claude` binary that
owned the `claude` invocation and replaced the whole system prompt via
`--system-prompt-file`).

## Why MCP instead of a launcher

Claude Code already ships a substantial system prompt, tool suite, subagents,
skills, plan mode, and hierarchical `CLAUDE.md` loading. A launcher that
replaced the system prompt had to re-supply everything Claude Code already
provides and own the process. The MCP model inverts that: basecamp contributes
only the **delta** Claude Code lacks — the project's related directories and its
custom context — and rides on top of everything native.

The trade is real: the server cannot replace or own the system prompt, it can
only augment. In exchange it is portable (one committed line of config),
survives Claude Code upgrades, and reaches sessions a launcher never could —
including Claude Code on the web, which reads project-scope `.mcp.json` straight
from the repo.

The design rests on one validated fact: **Claude Code injects an MCP server's
`instructions` field into context at session start**, capped at 2KB and
truncated. It is a real, automatic context channel — not merely a tool
registry. (Official MCP reference; injection behavior confirmed via
`anthropics/claude-code#30135`, where even a *disabled* server's instructions
were shown loading into the system prompt.)

## How it works

Two surfaces, both resolved from the `projects` section of
`~/.pi/basecamp/config.json` — the same resolution `pi/core/project/config.ts`
performs today, so basecamp config stays the single source of truth for a
project's `additionalDirs` and named context file.

**1. The `instructions` field** — 2KB cap, auto-injected at session start. A
router, not a payload: project identity, the list of related directories, and a
one-line pointer to the context resource. The injected text reads like:

> This project spans `~/code/foo`, `~/code/bar`, and `~/code/baz` — read and
> search them as relevant. Read the project context resource before starting
> substantial work.

**2. Resources** — read on demand via `ReadMcpResource` (no `@`-mention
required; the agent can pull them itself):

| Resource | Content |
| --- | --- |
| `basecamp://project/context` | the project's named context file plus discovered `AGENTS.md` / `CLAUDE.md` |
| `basecamp://project/dirs` *(optional)* | per-directory "what and why" annotations for the related directories |

The 2KB cap is why the design splits this way: the directory list and pointer
fit comfortably inside the field, while the bulkier context lives behind the
pointer as a resource.

## Out of scope (by decision)

- **Permissions.** Reading the related directories is the user's own grant, made
  in their `~/.claude/settings.json` — for example a `Read(~/code/**)` allow
  rule (user scope, `~/`-anchored) for promptless, read-only cross-repo search,
  paired with `deny` rules over secrets. The server never writes host
  permissions; it only makes the directories *known* so Claude reads them once
  the user's settings allow it.
- **Modes, launching, coordination state, dashboards.** The server is an
  awareness + context layer. Anything that mutates or orchestrates is a separate
  concern and, if it graduates at all, does so as an explicit tool — never as a
  silent side effect of loading context.

## Model-facing content principle

The text the server injects — the `instructions` field and resource bodies —
must read as clean, native project guidance. It carries project facts and
pointers, not basecamp/Pi runtime jargon, and never references Pi-only runtime
behavior. The MCP client already labels the source as the `basecamp` server, so
the injected text itself stays about the project, not about the tool delivering
it.
