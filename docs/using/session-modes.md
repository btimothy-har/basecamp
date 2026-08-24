# Session Modes & Working Styles

basecamp replaces Pi's default system prompt and assembles its own from layers: constraints, posture, style, capabilities, project context, and environment. Two of those layers are yours to choose: the **session mode** sets the agent's posture, and the **working style** sets its role. The full assembly is in [System Prompt](../architecture/system-prompt.md).

## Session Modes

The mode sets the agent's posture. Cycle between **analysis**, **explore**, and **work** with **shift+tab**:

| Mode | Posture |
|------|---------|
| **Analysis** | Research and data analysis: answer questions with evidence (queries, metrics, investigation), without implementing |
| **Explore** | Planning: understand the problem and design a plan before implementing |
| **Work** | Implement and integrate (the default) |

**Copilot** is a launch-only mode (`pi --copilot`) for steering work across a repo rather than implementing in-session. It keeps a current map of what's active, waiting, blocked, stale, or proposed, and turns the focus you choose into an execution-ready workstream that another session picks up. It doesn't write code itself; it stages work with `launch_workstream`. It's immutable (shift+tab can't enter or leave it) and takes precedence over `pi --workstream`.

## Working Styles

The style sets the agent's role. Set it per project with `working_style` (see [Projects](../configuration/projects.md)) or override at launch with `pi --style <name>`.

| Style | Role |
|-------|------|
| `engineering` | Primary engineer for the assigned task; the user is principal engineer for broader technical direction |
| `advisor` | Efficient discovery, direct communication, decision support |
| `logseq` | Knowledge-graph curation, structured entries, user-driven content approval |

Add a custom style as `{name}.md` under `~/.pi/basecamp/workspace/styles/`.
