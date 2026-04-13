# 04 — Port Observer Integration

## Goal

Migrate observer pipeline triggers from `companion/scripts/hook-process.sh` and `companion/scripts/pretool-ingest.sh` into `extension/src/observer.ts`.

## Sources

### 1. `plugins/companion/scripts/hook-process.sh`

Hooked on `PreCompact` and `SessionEnd`. Backgrounds `observer ingest --process` to run the full pipeline (ingest transcript + process/extract). Skips if `BASECAMP_OBSERVER_ENABLED != 1` or `BASECAMP_REFLECT == 1`.

### 2. `plugins/companion/scripts/pretool-ingest.sh`

Hooked on `PreToolUse` (bash only). Detects `task create --dispatch` in bash command input and backgrounds `observer ingest` (without `--process`) so the worker has recall access to the parent session's context before it starts.

The Claude Code version reads JSON from stdin to get `tool_name` and `tool_input.command`. In pi, this is a `tool_call` event with typed `event.input`.

## Target

**File:** `extension/src/observer.ts`

Export:

```typescript
export function registerObserver(pi: ExtensionAPI): void
```

### Implementation

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

function isObserverEnabled(): boolean {
  return process.env.BASECAMP_OBSERVER_ENABLED === "1"
    && process.env.BASECAMP_REFLECT !== "1";
}

/**
 * Background the observer pipeline. Fire-and-forget — errors are swallowed
 * (observer logs to its own log file).
 */
async function triggerIngest(pi: ExtensionAPI, process_flag: boolean): Promise<void> {
  const args = ["ingest"];
  if (process_flag) args.push("--process");

  try {
    // Fire and forget — don't await completion, don't block the session
    pi.exec("observer", args, { timeout: 300_000 }).catch(() => {});
  } catch {
    // Swallow — observer handles its own logging
  }
}

export function registerObserver(pi: ExtensionAPI) {
  // Trigger full pipeline on compaction
  pi.on("session_before_compact", async (_event, _ctx) => {
    if (!isObserverEnabled()) return;
    await triggerIngest(pi, true);
  });

  // Trigger full pipeline on session shutdown
  pi.on("session_shutdown", async (_event, _ctx) => {
    if (!isObserverEnabled()) return;
    await triggerIngest(pi, true);
  });

  // Pre-ingest before dispatch so workers have recall access
  pi.on("tool_call", async (event, _ctx) => {
    if (!isObserverEnabled()) return;
    if (!isToolCallEventType("bash", event)) return;

    const cmd = event.input.command || "";
    if (/worker\s+create\s+.*--dispatch/.test(cmd)) {
      await triggerIngest(pi, false);
    }
  });
}
```

### Key Differences from Shell Version

1. **No stdin JSON parsing** — pi provides typed `event.input.command`
2. **No `nohup` / backgrounding** — `pi.exec()` with `.catch(() => {})` achieves fire-and-forget. The exec runs in a child process and the promise is intentionally not awaited.
3. **No `cat` piping** — the shell version pipes hook stdin to `observer ingest`. The observer CLI reads the transcript path from `$BASECAMP_TRANSCRIPT_PATH` env var (set by session-init). In pi, the transcript path concept differs — verify that `observer ingest` can discover the session to ingest without stdin piping. If observer needs the session file path, pass it as an argument: `observer ingest --session <path>`. Check observer's CLI interface.
4. **Dispatch detection** — shell version checks for `task create --dispatch` but the basecamp CLI command is actually `worker create --dispatch`. Update the regex to match the actual command used.

### Open Questions for Implementation

- **Does `observer ingest` need the transcript/session path?** Check `observer/src/observer/cli/observer.py` for the `ingest` command's arguments. The shell version pipes hook JSON to stdin. In pi, you may need to pass `ctx.sessionManager.getSessionFile()` or `process.env.BASECAMP_TRANSCRIPT_PATH` as an argument.
- **Should `session_before_compact` trigger ingest?** The shell version fires on `PreCompact` which runs before compaction. The pi event `session_before_compact` can cancel compaction — we don't want to cancel, just trigger ingest. Alternatively, use `session_compact` (fires after) if the timing is less critical.

### Update `src/index.ts`

Uncomment the observer import and registration call.

## Acceptance Criteria

- [ ] `extension/src/observer.ts` exists and exports `registerObserver`
- [ ] Full pipeline triggered on compaction and shutdown (when observer enabled)
- [ ] Pre-ingest triggered on dispatch commands (when observer enabled)
- [ ] No ingest when `BASECAMP_OBSERVER_ENABLED != 1`
- [ ] No ingest when `BASECAMP_REFLECT == 1`
- [ ] `src/index.ts` imports and calls `registerObserver(pi)`
- [ ] Observer errors don't crash the extension or block the session
