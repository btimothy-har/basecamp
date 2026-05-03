---
name: pi-development
description: Developing pi extensions, skills, prompt templates, themes, and packages. Use when creating or modifying TypeScript extensions that register tools/commands/events, writing SKILL.md files, authoring prompt templates, building JSON themes, or packaging for distribution.
---

# Pi Development

Build extensions, skills, prompt templates, themes, and packages for the [pi coding agent](https://github.com/badlogic/pi-mono).

## Concepts

| Concept | What it is | Format |
|---------|-----------|--------|
| **Extension** | TypeScript module that adds tools, commands, shortcuts, event handlers, and custom UI | `.ts` file exporting a default function |
| **Skill** | On-demand capability package the agent loads when relevant | Directory with `SKILL.md` + optional scripts/references |
| **Prompt template** | Reusable prompt snippet expanded via `/name` | `.md` file with optional frontmatter |
| **Theme** | Color scheme for the TUI | `.json` file with 51 color tokens |
| **Package** | Bundles any combination of the above for distribution | npm or git repo with `package.json` manifest |

## Extensions — read [EXTENSIONS.md](references/EXTENSIONS.md)

TypeScript modules that extend pi's behavior. The entry point exports a default function receiving `ExtensionAPI`:

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

export default function (pi: ExtensionAPI) {
  pi.registerTool({ name: "my_tool", ... });
  pi.registerCommand("my-cmd", { ... });
  pi.on("tool_call", async (event, ctx) => { ... });
}
```

**Key capabilities:**
- Custom tools callable by the LLM (`pi.registerTool()`)
- Event interception — block/modify tool calls, inject context, customize compaction
- User interaction — dialogs, notifications, custom TUI components
- Custom commands — `/mycommand` registration
- Session persistence — state that survives restarts
- Custom rendering — control tool call/result display

**Locations:** `~/.pi/agent/extensions/` (global), `.pi/extensions/` (project), or via packages.

**Available imports:** `@mariozechner/pi-coding-agent` (types), `@sinclair/typebox` (schemas), `@mariozechner/pi-ai` (AI utilities like `StringEnum`), `@mariozechner/pi-tui` (TUI components). npm deps also work — add a `package.json` and `npm install`.

**Testing:** Use `pi -e ./my-extension.ts` for quick iteration. Place in auto-discovered locations for `/reload` support.

---

## Skills — read [SKILLS.md](references/SKILLS.md)

On-demand capability packages following the [Agent Skills standard](https://agentskills.io/specification). Only the description is in context at startup; full instructions load when needed.

```markdown
---
name: my-skill
description: What this skill does and when to use it. Be specific — this determines when the agent loads it.
---

# My Skill

## Usage
...
```

**Structure:** Directory with `SKILL.md` (required). Add `scripts/`, `references/`, `assets/` as needed. Use relative paths.

**Name rules:** 1-64 chars, lowercase `a-z`, `0-9`, hyphens only. Must match parent directory name.

**Locations:** `~/.pi/agent/skills/`, `.pi/skills/`, `.agents/skills/`, or via packages.

**Invocation:** `/skill:name` or automatic when task matches description.

---

## Prompt Templates — read [PROMPT_TEMPLATES.md](references/PROMPT_TEMPLATES.md)

Reusable prompts as Markdown files. Filename becomes the command (`review.md` → `/review`).

```markdown
---
description: Review staged git changes
---
Review the staged changes. Focus on: $@
```

**Arguments:** `$1`, `$2` for positional, `$@` for all args, `${@:N}` for slicing.

**Locations:** `~/.pi/agent/prompts/`, `.pi/prompts/`, or via packages.

---

## Themes — read [THEMES.md](references/THEMES.md)

JSON files defining 51 color tokens for the TUI. Must define all tokens.

```json
{
  "$schema": "https://raw.githubusercontent.com/badlogic/pi-mono/main/packages/coding-agent/src/modes/interactive/theme/theme-schema.json",
  "name": "my-theme",
  "vars": { "primary": "#00aaff" },
  "colors": {
    "accent": "primary",
    "border": "primary",
    ...
  }
}
```

**Color formats:** Hex (`"#ff0000"`), 256-color index (`242`), variable reference (`"primary"`), or default (`""`).

**Hot reload:** Active custom theme files are reloaded automatically on save.

---

## Packages — read [PACKAGES.md](references/PACKAGES.md)

Bundle extensions, skills, prompts, and themes for distribution via npm or git.

```json
{
  "name": "my-pi-package",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extensions"],
    "skills": ["./skills"],
    "prompts": ["./prompts"],
    "themes": ["./themes"]
  }
}
```

**Peer deps:** List `@mariozechner/pi-coding-agent`, `@sinclair/typebox`, `@mariozechner/pi-ai`, `@mariozechner/pi-tui` as `peerDependencies` with `"*"`.

**Install:** `pi install npm:pkg` or `pi install git:github.com/user/repo`.

---

## Quick Reference

### Common Extension Patterns

| Pattern | API |
|---------|-----|
| Add a tool | `pi.registerTool({ name, description, parameters, execute })` |
| Add a command | `pi.registerCommand("name", { description, handler })` |
| Block dangerous ops | `pi.on("tool_call", ...)` → return `{ block: true, reason }` |
| Inject context per-turn | `pi.on("before_agent_start", ...)` → return `{ systemPrompt }` |
| React to model change | `pi.on("model_select", ...)` |
| Persist state | `pi.appendEntry("type", data)` — restore in `session_start` |
| Show status | `ctx.ui.setStatus("id", text)` |
| Show widget | `ctx.ui.setWidget("id", lines)` |
| Custom UI | `ctx.ui.custom((tui, theme, kb, done) => component)` |
| Dynamic tools | `pi.setActiveTools(names)` |
| Send user message | `pi.sendUserMessage(text, { deliverAs })` |

### Tool Schema Tips

- Use `Type.Object({})` from `@sinclair/typebox` for parameters
- Use `StringEnum(["a", "b"] as const)` from `@mariozechner/pi-ai` — `Type.Union`/`Type.Literal` breaks Google
- Use `Type.Optional(Type.String())` for optional params
- Always truncate large tool output (50KB / 2000 lines max)
- Use `withFileMutationQueue(path, fn)` if your tool writes files

### Event Lifecycle

```
session_start → resources_discover → input → before_agent_start →
agent_start → turn_start → context → tool_call → tool_result →
turn_end → agent_end → session_shutdown
```

## Source Code — read [CODEBASE.md](references/CODEBASE.md)

When the bundled docs aren't enough, clone the pi-mono repo and read the source:

```bash
git clone --depth 1 https://github.com/badlogic/pi-mono /tmp/pi-mono
```

Key files to investigate:
- **Extension types/events:** `packages/coding-agent/src/core/extensions/types.ts`
- **Built-in tool implementations:** `packages/coding-agent/src/core/tools/*.ts`
- **System prompt assembly:** `packages/coding-agent/src/core/system-prompt.ts`
- **TUI components:** `packages/tui/src/components/*.ts`
- **50+ example extensions:** `packages/coding-agent/examples/extensions/`
