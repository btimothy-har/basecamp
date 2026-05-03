# Pi Codebase Reference

When the bundled docs aren't enough, clone the pi-mono repo and investigate the source directly.

## Cloning

```bash
git clone https://github.com/badlogic/pi-mono /tmp/pi-mono
cd /tmp/pi-mono
```

Shallow clone is fine for reading: `git clone --depth 1 ...`

## Repository Layout

```
pi-mono/
├── AGENTS.md                  # Dev rules and contribution guidelines
├── CONTRIBUTING.md
├── packages/
│   ├── ai/                    # LLM provider abstraction
│   │   ├── src/
│   │   │   ├── types.ts       # Base message types, Usage, Model, Api, KnownProvider
│   │   │   ├── stream.ts      # Streaming orchestration
│   │   │   ├── models.ts      # Model registry
│   │   │   ├── index.ts       # Public exports (StringEnum, etc.)
│   │   │   ├── providers/     # Provider implementations
│   │   │   │   ├── anthropic.ts
│   │   │   │   ├── openai-responses.ts
│   │   │   │   ├── google.ts
│   │   │   │   ├── faux.ts              # Mock provider for tests
│   │   │   │   └── transform-messages.ts # Cross-provider message conversion
│   │   │   └── utils/         # JSON parsing, overflow detection, etc.
│   │   └── test/              # Provider integration tests
│   │
│   ├── agent/                 # Agent loop and message types
│   │   └── src/
│   │       ├── agent.ts       # Core agent loop
│   │       ├── agent-loop.ts  # Turn execution
│   │       └── types.ts       # AgentMessage union type
│   │
│   ├── tui/                   # Terminal UI components
│   │   └── src/
│   │       ├── index.ts       # All public exports
│   │       ├── tui.ts         # TUI runtime (rendering, focus, input)
│   │       ├── keys.ts        # Key detection (matchesKey, Key)
│   │       ├── keybindings.ts # Keybinding manager
│   │       ├── utils.ts       # visibleWidth, truncateToWidth, wrapTextWithAnsi
│   │       └── components/
│   │           ├── text.ts
│   │           ├── box.ts
│   │           ├── editor.ts
│   │           ├── input.ts
│   │           ├── markdown.ts
│   │           ├── select-list.ts
│   │           ├── settings-list.ts
│   │           ├── spacer.ts
│   │           └── image.ts
│   │
│   └── coding-agent/         # CLI, extensions, tools, interactive mode
│       ├── src/
│       │   ├── index.ts       # Public API exports
│       │   ├── main.ts        # CLI entry point
│       │   ├── config.ts      # Package asset resolution
│       │   ├── core/
│       │   │   ├── agent-session.ts         # Session orchestration
│       │   │   ├── agent-session-runtime.ts # Multi-session runtime
│       │   │   ├── session-manager.ts       # Session tree, entries, persistence
│       │   │   ├── messages.ts              # Extended message types
│       │   │   ├── system-prompt.ts         # Default system prompt assembly
│       │   │   ├── model-registry.ts        # Model discovery and auth
│       │   │   ├── model-resolver.ts        # Default model resolution
│       │   │   ├── settings-manager.ts      # Settings loading and merging
│       │   │   ├── resource-loader.ts       # Extension/skill/prompt/theme discovery
│       │   │   ├── skills.ts                # Skill loading and validation
│       │   │   ├── prompt-templates.ts      # Template expansion
│       │   │   ├── keybindings.ts           # Keybinding defaults and migration
│       │   │   ├── sdk.ts                   # createAgentSession / SDK entry
│       │   │   ├── extensions/
│       │   │   │   ├── types.ts             # ExtensionAPI, ExtensionContext, all event types
│       │   │   │   ├── runner.ts            # Event dispatch, tool/command registration
│       │   │   │   ├── loader.ts            # Extension file discovery and loading
│       │   │   │   └── wrapper.ts           # Extension lifecycle wrapper
│       │   │   ├── tools/
│       │   │   │   ├── bash.ts              # bash tool + BashToolDetails
│       │   │   │   ├── read.ts              # read tool + ReadToolDetails
│       │   │   │   ├── edit.ts              # edit tool (diff rendering)
│       │   │   │   ├── write.ts             # write tool
│       │   │   │   ├── grep.ts              # grep tool + GrepToolDetails
│       │   │   │   ├── find.ts              # find tool + FindToolDetails
│       │   │   │   ├── ls.ts                # ls tool + LsToolDetails
│       │   │   │   ├── truncate.ts          # truncateHead, truncateTail
│       │   │   │   ├── file-mutation-queue.ts # withFileMutationQueue
│       │   │   │   ├── path-utils.ts        # Path resolution helpers
│       │   │   │   └── render-utils.ts      # Shared tool rendering
│       │   │   └── compaction/
│       │   │       ├── compaction.ts         # Auto and manual compaction
│       │   │       └── branch-summarization.ts
│       │   ├── modes/
│       │   │   ├── interactive/
│       │   │   │   └── interactive-mode.ts  # TUI mode
│       │   │   ├── print-mode.ts            # -p mode
│       │   │   └── rpc/
│       │   │       ├── rpc-mode.ts          # RPC server
│       │   │       └── rpc-types.ts         # RPC protocol types
│       │   └── utils/
│       │       ├── git.ts                   # Git helpers
│       │       ├── shell.ts                 # Shell detection
│       │       └── frontmatter.ts           # YAML frontmatter parsing
│       ├── docs/              # All documentation (.md)
│       ├── examples/
│       │   ├── extensions/    # 50+ example extensions
│       │   └── sdk/           # SDK usage examples
│       └── test/              # Test suite (vitest)
```

## Key Source Files to Investigate

### Understanding extension types and events

**Start here:** `packages/coding-agent/src/core/extensions/types.ts`

Contains all TypeScript interfaces: `ExtensionAPI`, `ExtensionContext`, `ExtensionCommandContext`, all event types (`ToolCallEvent`, `ToolResultEvent`, `SessionStartEvent`, etc.), and return types.

### Understanding tool definitions

**Built-in tools:** `packages/coding-agent/src/core/tools/*.ts`

Each tool file exports a factory (`createBashTool`, `createReadTool`, etc.) and its details type (`BashToolDetails`, `ReadToolDetails`). Reading these shows the exact result shape your override must match.

### Understanding the system prompt

**System prompt assembly:** `packages/coding-agent/src/core/system-prompt.ts`

Shows how tools, skills, and context are wired into the prompt. Useful when writing extensions that modify the system prompt via `before_agent_start`.

### Understanding session structure

**Session manager:** `packages/coding-agent/src/core/session-manager.ts`

Entry types, tree navigation, context building. The authoritative reference for session file format.

**Message types:** `packages/coding-agent/src/core/messages.ts` (extended) and `packages/ai/src/types.ts` (base).

### Understanding the extension runner

**Extension lifecycle:** `packages/coding-agent/src/core/extensions/runner.ts`

How events are dispatched, tools registered, commands bound. Shows the exact contract between extensions and the runtime.

### Understanding TUI components

**Component implementations:** `packages/tui/src/components/*.ts`

Read `select-list.ts` and `settings-list.ts` to understand the full API of these components (constructor options, theme callbacks, event handlers).

### Understanding model/provider integration

**Model registry:** `packages/coding-agent/src/core/model-registry.ts`

How models are discovered, resolved, and authenticated.

**Provider implementations:** `packages/ai/src/providers/*.ts`

Streaming, message conversion, auth handling per provider.

## Example Extensions as Learning Material

The `examples/extensions/` directory has 50+ working extensions covering every API surface:

| What you want to learn | Read these |
|------------------------|-----------|
| Basic tool registration | `hello.ts`, `question.ts` |
| Tool with user interaction | `questionnaire.ts`, `qna.ts` |
| Stateful tools with session persistence | `todo.ts` |
| Dynamic tool registration | `dynamic-tools.ts` |
| Tool override (replace built-in) | `tool-override.ts` |
| Output truncation | `truncated-tool.ts` |
| Event interception | `permission-gate.ts`, `protected-paths.ts` |
| System prompt modification | `pirate.ts`, `system-prompt-header.ts` |
| Input transformation | `input-transform.ts` |
| Custom compaction | `custom-compaction.ts` |
| Session management | `confirm-destructive.ts`, `git-checkpoint.ts` |
| Custom UI (SelectList, loaders) | `preset.ts`, `tools.ts`, `qna.ts` |
| Custom editor | `modal-editor.ts`, `rainbow-editor.ts` |
| Widgets and status | `status-line.ts`, `widget-placement.ts` |
| Custom footer | `custom-footer.ts` |
| Overlays | `overlay-test.ts`, `overlay-qa-tests.ts` |
| Message rendering | `message-renderer.ts` |
| Inter-extension events | `event-bus.ts` |
| Full complex extension | `plan-mode/` (directory) |
| SSH/remote execution | `ssh.ts` |
| Provider registration | `custom-provider-anthropic/` |
| Send messages programmatically | `send-user-message.ts`, `file-trigger.ts` |
| Reload runtime | `reload-runtime.ts` |

## Setup for Local Development

If you need to build and test:

```bash
cd /tmp/pi-mono
npm install
npm run build
```

Run from source:

```bash
/tmp/pi-mono/pi-test.sh
```

Run a specific test:

```bash
cd /tmp/pi-mono/packages/coding-agent
npx tsx ../../node_modules/vitest/dist/cli.js --run test/specific.test.ts
```

## Tips

- **Type definitions:** Check `node_modules/@mariozechner/pi-coding-agent/dist/` in your project for compiled types when the source isn't available
- **Public API:** `packages/coding-agent/src/index.ts` re-exports everything intended for extension authors
- **Faux provider:** `packages/ai/src/providers/faux.ts` is a mock LLM for tests — use it to understand the streaming protocol
- **Never run `npm test` or `npm run dev`** in the pi-mono repo (per AGENTS.md guidelines)
