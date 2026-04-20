# Extensions Reference

## Structure

**Single file:**
```
~/.pi/agent/extensions/my-extension.ts
```

**Directory:**
```
my-extension/
├── index.ts        # Entry point
├── tools.ts
└── utils.ts
```

**With npm dependencies:**
```
my-extension/
├── package.json
├── node_modules/
└── src/index.ts
```

```json
{
  "name": "my-extension",
  "dependencies": { "zod": "^3.0.0" },
  "pi": { "extensions": ["./src/index.ts"] }
}
```

## Extension Entry Point

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  // Subscribe to events
  pi.on("event_name", async (event, ctx) => { ... });

  // Register tools, commands, shortcuts, flags
  pi.registerTool({ ... });
  pi.registerCommand("name", { ... });
  pi.registerShortcut("ctrl+x", { ... });
  pi.registerFlag("my-flag", { ... });
}
```

Extensions are loaded via [jiti](https://github.com/unjs/jiti) — TypeScript works without compilation.

## Registering Tools

```typescript
import { Type } from "@sinclair/typebox";
import { StringEnum } from "@mariozechner/pi-ai";

pi.registerTool({
  name: "my_tool",
  label: "My Tool",
  description: "What this tool does (shown to LLM)",
  promptSnippet: "One-line entry for Available tools section",
  promptGuidelines: ["Bullet for the Guidelines section when tool is active"],
  parameters: Type.Object({
    action: StringEnum(["list", "add"] as const),  // StringEnum for Google compat
    text: Type.Optional(Type.String()),
  }),
  async execute(toolCallId, params, signal, onUpdate, ctx) {
    // Stream progress
    onUpdate?.({ content: [{ type: "text", text: "Working..." }] });

    // Check cancellation
    if (signal?.aborted) return { content: [{ type: "text", text: "Cancelled" }] };

    return {
      content: [{ type: "text", text: "Done" }],  // Sent to LLM
      details: { result: "..." },                   // For rendering & state
    };
  },
});
```

**Critical rules:**
- Use `StringEnum` from `@mariozechner/pi-ai` for string enums — `Type.Union`/`Type.Literal` breaks Google's API
- Signal errors by **throwing**, not by return values
- Truncate output to 50KB / 2000 lines — use `truncateHead()` or `truncateTail()` from pi
- Use `withFileMutationQueue(absolutePath, fn)` if writing files, so parallel tool calls don't clobber each other
- `pi.registerTool()` works both during load and after startup (dynamically)

### Output Truncation

```typescript
import { truncateHead, DEFAULT_MAX_BYTES, DEFAULT_MAX_LINES, formatSize } from "@mariozechner/pi-coding-agent";

const truncation = truncateHead(output, { maxLines: DEFAULT_MAX_LINES, maxBytes: DEFAULT_MAX_BYTES });
let result = truncation.content;
if (truncation.truncated) {
  result += `\n[Truncated: ${truncation.outputLines}/${truncation.totalLines} lines (${formatSize(truncation.outputBytes)}/${formatSize(truncation.totalBytes)})]`;
}
```

### File Mutation Queue

```typescript
import { withFileMutationQueue } from "@mariozechner/pi-coding-agent";
import { resolve } from "node:path";

async execute(_id, params, _signal, _onUpdate, ctx) {
  const absolutePath = resolve(ctx.cwd, params.path);
  return withFileMutationQueue(absolutePath, async () => {
    // Read-modify-write inside the queue
    const current = await readFile(absolutePath, "utf8");
    await writeFile(absolutePath, current.replace(params.old, params.new));
    return { content: [{ type: "text", text: "Updated" }], details: {} };
  });
}
```

### Overriding Built-in Tools

Register a tool with the same name as a built-in (`read`, `bash`, `edit`, `write`, `grep`, `find`, `ls`). Rendering slots (`renderCall`, `renderResult`) fall back to the built-in renderer if omitted.

### Custom Rendering

```typescript
import { Text } from "@mariozechner/pi-tui";

renderCall(args, theme, context) {
  const text = (context.lastComponent as Text | undefined) ?? new Text("", 0, 0);
  text.setText(theme.fg("toolTitle", theme.bold("my_tool ")) + theme.fg("muted", args.action));
  return text;
},

renderResult(result, { expanded, isPartial }, theme, context) {
  if (isPartial) return new Text(theme.fg("warning", "Processing..."), 0, 0);
  let text = theme.fg("success", "✓ Done");
  if (expanded && result.details?.items) {
    text += result.details.items.map(i => "\n  " + theme.fg("dim", i)).join("");
  }
  return new Text(text, 0, 0);
}
```

## Registering Commands

```typescript
pi.registerCommand("stats", {
  description: "Show session statistics",
  handler: async (args, ctx) => {
    const count = ctx.sessionManager.getEntries().length;
    ctx.ui.notify(`${count} entries`, "info");
  },
  // Optional: argument auto-completion
  getArgumentCompletions: (prefix) => {
    const items = ["dev", "staging", "prod"].map(e => ({ value: e, label: e }));
    return items.filter(i => i.value.startsWith(prefix)) || null;
  },
});
```

Command handlers receive `ExtensionCommandContext` (extends `ExtensionContext`) with additional methods: `ctx.waitForIdle()`, `ctx.newSession()`, `ctx.fork()`, `ctx.navigateTree()`, `ctx.switchSession()`, `ctx.reload()`.

## Events

### Lifecycle

```
session_start → resources_discover → [user prompt] → input →
before_agent_start → agent_start → turn_start → context →
before_provider_request → tool_execution_start → tool_call →
tool_execution_update → tool_result → tool_execution_end →
turn_end → agent_end → session_shutdown
```

### Key Events

| Event | Use case | Return |
|-------|----------|--------|
| `session_start` | Initialize state, restore from entries | - |
| `resources_discover` | Contribute skill/prompt/theme paths | `{ skillPaths, promptPaths, themePaths }` |
| `input` | Transform/intercept user input | `{ action: "continue" \| "transform" \| "handled" }` |
| `before_agent_start` | Inject messages, modify system prompt | `{ message?, systemPrompt? }` |
| `context` | Modify messages before LLM call | `{ messages }` |
| `tool_call` | Block or modify tool args (mutable `event.input`) | `{ block: true, reason? }` |
| `tool_result` | Modify tool output | `{ content?, details?, isError? }` |
| `model_select` | React to model changes | - |
| `session_shutdown` | Cleanup | - |

### Type-safe Tool Events

```typescript
import { isToolCallEventType, isBashToolResult } from "@mariozechner/pi-coding-agent";

pi.on("tool_call", (event, ctx) => {
  if (isToolCallEventType("bash", event)) {
    // event.input is typed as { command: string; timeout?: number }
    if (event.input.command.includes("rm -rf"))
      return { block: true, reason: "Dangerous" };
  }
});

pi.on("tool_result", (event, ctx) => {
  if (isBashToolResult(event)) {
    // event.details is typed as BashToolDetails
  }
});
```

## ExtensionContext (ctx)

| Property/Method | Description |
|-----------------|-------------|
| `ctx.ui` | UI methods (dialogs, status, widgets, custom components) |
| `ctx.hasUI` | `false` in print/JSON mode |
| `ctx.cwd` | Current working directory |
| `ctx.sessionManager` | Read-only session state |
| `ctx.modelRegistry` / `ctx.model` | Model access |
| `ctx.signal` | Abort signal during active turns |
| `ctx.isIdle()` / `ctx.abort()` | Control flow |
| `ctx.getSystemPrompt()` | Current effective system prompt |
| `ctx.getContextUsage()` | Token usage info |
| `ctx.compact()` | Trigger compaction |
| `ctx.shutdown()` | Graceful exit |

### UI Methods

```typescript
// Dialogs
const choice = await ctx.ui.select("Pick:", ["A", "B"]);
const ok = await ctx.ui.confirm("Title", "Message");
const name = await ctx.ui.input("Name:", "placeholder");
const text = await ctx.ui.editor("Edit:", "prefilled");

// With timeout
const ok = await ctx.ui.confirm("Title", "Msg", { timeout: 5000 });

// Non-blocking
ctx.ui.notify("Done!", "info");  // "info" | "warning" | "error"

// Persistent UI
ctx.ui.setStatus("my-ext", "Processing...");
ctx.ui.setWidget("my-widget", ["Line 1", "Line 2"]);
ctx.ui.setWidget("my-widget", lines, { placement: "belowEditor" });

// Custom component (replaces editor until done)
const result = await ctx.ui.custom<T>((tui, theme, keybindings, done) => {
  return component;  // { render, invalidate, handleInput }
});

// Overlay mode
const result = await ctx.ui.custom<T>(factory, {
  overlay: true,
  overlayOptions: { anchor: "center", width: "50%" },
});
```

## ExtensionAPI Methods

| Method | Description |
|--------|-------------|
| `pi.on(event, handler)` | Subscribe to events |
| `pi.registerTool(def)` | Register LLM-callable tool |
| `pi.registerCommand(name, opts)` | Register `/command` |
| `pi.registerShortcut(key, opts)` | Register keyboard shortcut |
| `pi.registerFlag(name, opts)` | Register CLI flag |
| `pi.registerMessageRenderer(type, fn)` | Custom message rendering |
| `pi.registerProvider(name, config)` | Register/override model provider |
| `pi.sendMessage(msg, opts?)` | Inject custom message |
| `pi.sendUserMessage(content, opts?)` | Send user message |
| `pi.appendEntry(type, data?)` | Persist extension state |
| `pi.setSessionName(name)` | Set session display name |
| `pi.setLabel(id, label)` | Bookmark an entry |
| `pi.exec(cmd, args, opts?)` | Execute shell command |
| `pi.getActiveTools()` / `pi.setActiveTools(names)` | Manage tools |
| `pi.getAllTools()` | List all tools with metadata |
| `pi.getCommands()` | List all slash commands |
| `pi.setModel(model)` | Switch model |
| `pi.getThinkingLevel()` / `pi.setThinkingLevel(level)` | Thinking control |
| `pi.events` | Inter-extension event bus |

## State Management

Store state in tool result `details` for proper branching:

```typescript
let items: string[] = [];

pi.on("session_start", async (_event, ctx) => {
  items = [];
  for (const entry of ctx.sessionManager.getBranch()) {
    if (entry.type === "message" && entry.message.role === "toolResult"
        && entry.message.toolName === "my_tool") {
      items = entry.message.details?.items ?? [];
    }
  }
});

pi.registerTool({
  name: "my_tool",
  async execute(id, params) {
    items.push("new");
    return { content: [...], details: { items: [...items] } };
  },
});
```

## Mode Behavior

| Mode | UI | Notes |
|------|-----|-------|
| Interactive | Full TUI | Normal |
| RPC (`--mode rpc`) | JSON protocol | Host handles UI |
| JSON (`--mode json`) | No-op | Event stream |
| Print (`-p`) | No-op | Can't prompt |

Check `ctx.hasUI` before using UI methods.
