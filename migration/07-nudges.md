# 07 — Port Skill Nudging

## Goal

Migrate the `tool_call` skill-reminder logic from `pi-eng/extension/index.ts` into `extension/src/nudges.ts`.

## Source

**File:** `plugins/pi-eng/extension/index.ts` — `tool_call` handler

**Behavior:** When the LLM calls `write` or `edit` on a `.py` file, sends a steering message suggesting `/skill:python-development`. Same for `.sql` → `/skill:sql`.

## Target

**File:** `extension/src/nudges.ts`

Export:

```typescript
export function registerNudges(pi: ExtensionAPI): void
```

### Implementation

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

const NUDGES: Record<string, string> = {
  ".py": "Python file detected — consider loading /skill:python-development for best practices.",
  ".sql": "SQL file detected — consider loading /skill:sql for best practices.",
};

export function registerNudges(pi: ExtensionAPI) {
  // Track which extensions have already been nudged this session
  // to avoid repeated noise
  const nudged = new Set<string>();

  pi.on("session_start", async () => {
    nudged.clear();
  });

  pi.on("tool_call", async (event, _ctx) => {
    if (event.toolName !== "write" && event.toolName !== "edit") return;

    const filePath: string = (event.input as { path?: string }).path || "";

    for (const [ext, message] of Object.entries(NUDGES)) {
      if (filePath.endsWith(ext) && !nudged.has(ext)) {
        nudged.add(ext);
        pi.sendMessage(message, { deliverAs: "steer" });
        break;
      }
    }
  });
}
```

### Improvements Over Original

- **Deduplication:** The original sends the nudge on *every* `.py`/`.sql` write/edit. This version tracks which extensions have been nudged and only fires once per session per file type. This prevents chat pollution during multi-file edits.
- **Extensible:** The `NUDGES` map makes it easy to add more file-type → skill mappings.
- **Session reset:** Nudge tracking resets on `session_start` so a new session gets fresh nudges.

### Update `src/index.ts`

Uncomment the nudges import and registration call.

## Acceptance Criteria

- [ ] `extension/src/nudges.ts` exists and exports `registerNudges`
- [ ] Nudge fires once per file extension per session
- [ ] `.py` → python-development skill suggestion
- [ ] `.sql` → sql skill suggestion
- [ ] No nudge on second `.py` edit in same session
- [ ] `src/index.ts` imports and calls `registerNudges(pi)`
