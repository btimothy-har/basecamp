# 05 — Port Inter-Agent Messaging

## Goal

Migrate inbox checking from `companion/scripts/check-inbox.sh` into `extension/src/messaging.ts`.

## Source

**File:** `plugins/companion/scripts/check-inbox.sh`

**Behavior:**
- Called in two modes: `all` (reads `*.msg` + `*.immediate` files) and `immediate` (reads `*.immediate` only)
- Hooked on `PostToolUse` with mode `immediate` — checks after every tool call
- Hooked on `Stop` with mode `all` — checks at session end
- Reads files from `$BASECAMP_INBOX_DIR`, concatenates them with `---` separators, deletes consumed files
- Outputs JSON `additionalContext` so Claude sees the messages

**Delivery semantics:**
- `.immediate` files: delivered at next tool call (urgent interruptions)
- `.msg` files: delivered at session boundaries (normal messages)

## Target

**File:** `extension/src/messaging.ts`

Export:

```typescript
export function registerMessaging(pi: ExtensionAPI): void
```

### Implementation

```typescript
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs/promises";
import * as path from "node:path";

async function checkInbox(
  pi: ExtensionAPI,
  mode: "all" | "immediate",
): Promise<void> {
  const inboxDir = process.env.BASECAMP_INBOX_DIR;
  if (!inboxDir) return;

  let files: string[];
  try {
    const entries = await fs.readdir(inboxDir);
    if (mode === "immediate") {
      files = entries.filter(f => f.endsWith(".immediate")).sort();
    } else {
      files = entries.filter(f => f.endsWith(".msg") || f.endsWith(".immediate")).sort();
    }
  } catch {
    return; // Directory doesn't exist or isn't readable
  }

  if (files.length === 0) return;

  const messages: string[] = [];
  for (const file of files) {
    const filePath = path.join(inboxDir, file);
    try {
      const content = await fs.readFile(filePath, "utf8");
      await fs.unlink(filePath);
      if (content.trim()) messages.push(content.trim());
    } catch {
      // File disappeared between readdir and read — ignore
    }
  }

  if (messages.length === 0) return;

  const combined = messages.join("\n---\n");

  // Inject as a message the LLM will see
  pi.sendMessage({
    customType: "basecamp-inbox",
    content: `## Inbox Messages\n\n${combined}`,
    display: true,
  }, {
    deliverAs: mode === "immediate" ? "steer" : "followUp",
    triggerTurn: true,
  });
}

export function registerMessaging(pi: ExtensionAPI) {
  // Check for immediate messages after each tool execution
  pi.on("tool_execution_end", async (_event, _ctx) => {
    await checkInbox(pi, "immediate");
  });

  // Check all messages when agent finishes
  pi.on("agent_end", async (_event, _ctx) => {
    await checkInbox(pi, "all");
  });
}
```

### Key Differences from Shell Version

1. **Event mapping:**
   - `PostToolUse` → `tool_execution_end` (fires after each tool completes)
   - `Stop` → `agent_end` (fires when agent finishes all tool calls for a prompt)

2. **Message injection:**
   - Shell: stdout JSON with `additionalContext`
   - Pi: `pi.sendMessage()` with `deliverAs: "steer"` (immediate) or `deliverAs: "followUp"` (all)

3. **Message visibility:** Using `display: true` means inbox messages appear in the TUI, which is an improvement over the shell version where `additionalContext` was invisible to the user.

4. **Delivery timing:**
   - `"steer"` delivers after the current turn's tool calls finish, before the next LLM call — equivalent to the `PostToolUse` hook
   - `"followUp"` delivers when agent is fully idle — equivalent to `Stop` hook
   - `triggerTurn: true` ensures the LLM processes the messages even if it was about to stop

### Design Decisions

- Using `tool_execution_end` instead of `tool_result` because we want post-execution timing, not result modification
- The `agent_end` check with `deliverAs: "followUp"` ensures all pending messages are seen even if no more tool calls happen
- File deletion is atomic per-file — if the process crashes mid-read, some messages may be re-delivered (same as shell version)

### Update `src/index.ts`

Uncomment the messaging import and registration call.

## Acceptance Criteria

- [ ] `extension/src/messaging.ts` exists and exports `registerMessaging`
- [ ] `.immediate` files consumed after each tool execution
- [ ] `.msg` files consumed when agent finishes
- [ ] Messages injected into conversation via `sendMessage`
- [ ] Files deleted after consumption
- [ ] No errors when inbox directory doesn't exist
- [ ] `src/index.ts` imports and calls `registerMessaging(pi)`
