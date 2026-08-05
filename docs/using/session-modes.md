# Session Modes & Working Styles

basecamp replaces Pi's default system prompt and assembles its own from layers — constraints, posture, style, capabilities, project context, and environment. Two of those layers are yours to choose: the **session mode** sets the agent's posture, and the **working style** sets its role. The full assembly is in [System Prompt](../architecture/system-prompt.md).

## Session Modes

The mode sets the agent's posture. It's shown as a tag in the footer (`[analysis]`, `[explore]`, `[copilot]`); **work** has no tag because it's the default. Cycle between them with **shift+tab**:

| Mode | Footer | Posture |
|------|--------|---------|
| **Analysis** | `[analysis]` | Read-only — investigate and gather evidence, don't implement |
| **Explore** | `[explore]` | Planning — discuss and design before implementing |
| **Work** | — | Implement and integrate (the default) |

**Copilot** is a separate, launch-only mode (`pi --copilot`): shift+tab can't enter or leave it, and instead of implementing in-session it stages execution-ready workstreams. `pi --copilot` takes precedence over `pi --workstream`.

## Working Styles

The style sets the agent's role. Set it per project with `working_style` (see [Projects](../configuration/projects.md)) or override at launch with `pi --style <name>`.

| Style | Role |
|-------|------|
| `engineering` | Partner — collaborative work, code quality and file-focus, task tracking, git workflow |
| `advisor` | Advisor — efficient discovery, direct communication, decision support |
| `logseq` | Knowledge-graph curation — structured entries, user-driven content approval |

Add a custom style as `{name}.md` under `~/.pi/basecamp/workspace/styles/`.
