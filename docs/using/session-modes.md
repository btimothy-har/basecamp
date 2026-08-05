# Prompt System

basecamp replaces the default system prompt via a `before_agent_start` hook. This gives you:

- **Full control** — Define how the agent approaches work, not defaults
- **Consistency** — Same behavior across sessions; immune to upstream prompt changes
- **Customization** — Prompts designed for your specific workflow

Pi's skill and agent listings are sourced dynamically and included in the assembled prompt; tool contracts reach the model through the API tools array and are never listed in the prompt.

## Prompt Assembly

The system prompt is assembled from layered sources:

```
mode prompt, plus read-only constraints when applicable
         ↓
working style prompt, or subagent prompt for dispatched agents
         ↓
voice.md (output shape; primary sessions) then craft.md (code quality; always)
         ↓
environment.md (CLI usage, Python/uv)
         ↓
capabilities index (skills and parent-session agents; tool contracts ride the API tools array)
         ↓
project context (configured context plus AGENTS.md/CLAUDE.md)
         ↓
runtime environment (paths, platform, date, git/worktree state)
```

Built-in prompt files can be overridden by creating matching files under `~/.pi/basecamp/workspace/prompts/` (for example, `~/.pi/basecamp/workspace/prompts/environment.md` or `~/.pi/basecamp/workspace/prompts/modes/work.md`).

## Session Modes

The session mode sets the agent's posture and is shown in the footer. Cycle between `analysis`, `explore` (planning), and `work` (the default) with shift+tab. The primary session integrates all work; dispatched agents operate in disposable workspaces and deliver branches (workers) or reports (everyone else).

`copilot` is a locked, launch-only mode: start it with `pi --copilot`. It is immutable — shift+tab can neither enter nor leave it — and the `plan()` handoff is disabled in it (a copilot session stages execution-ready workstreams with `launch_workstream` instead of implementing in-session). `pi --copilot` takes precedence over `pi --workstream` if both are passed.

## Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality and file-focus guidance, task tracking and git workflow |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles as `{name}.md` files in `~/.pi/basecamp/workspace/styles/`.

## File-Length Guidance

Engineering sessions and mutative workers use soft caps of 350 lines for TypeScript and HTML, 400 for shell, 800 for SQL, and 500 for CSS, Python, and other recognized source types. Tighter project instructions take precedence. The cap is a module-design forcing function: split along responsibility seams rather than compressing formatting or creating continuation files.

After a successful structured `edit` or `write`, Basecamp checks the resulting recognized source file and sends the agent one hidden reminder while it remains over its cap. The edit always succeeds; the reminder neither blocks the tool nor replaces project lint or CI. Unlisted file types are exempt, and mutations made through bash or external generators are not attributed to this hook.
