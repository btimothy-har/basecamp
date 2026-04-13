# 06 — Port Worker Lifecycle

## Goal

Migrate worker close-on-exit from `companion/scripts/session-close.sh` into `extension/src/workers.ts`.

## Source

**File:** `plugins/companion/scripts/session-close.sh`

**Behavior:** On `SessionEnd`, if `$BASECAMP_WORKER_NAME` is set (meaning this is a dispatched worker session, not the orchestrator), runs `basecamp worker close` to update the worker index entry status from `dispatched` to `closed`.

This is a 2-line shell script:
```bash
if [ -n "$BASECAMP_WORKER_NAME" ]; then
  basecamp worker close 2>/dev/null || true
fi
```

## Target

**File:** `extension/src/workers.ts`

Export:

```typescript
export function registerWorkers(pi: ExtensionAPI): void
```

### Implementation

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export function registerWorkers(pi: ExtensionAPI) {
  pi.on("session_shutdown", async (_event, _ctx) => {
    const workerName = process.env.BASECAMP_WORKER_NAME;
    if (!workerName) return;

    try {
      await pi.exec("basecamp", ["worker", "close"], { timeout: 5_000 });
    } catch {
      // Best-effort — worker index update is non-critical
    }
  });
}
```

### Notes

- This is the simplest migration — one event, one exec, one guard
- `session_shutdown` fires on Ctrl+C, Ctrl+D, and SIGTERM — covers all exit paths
- Timeout of 5s prevents hanging on shutdown
- Errors are swallowed — if the worker index can't be updated, the session still closes cleanly

### Update `src/index.ts`

Uncomment the workers import and registration call.

## Acceptance Criteria

- [ ] `extension/src/workers.ts` exists and exports `registerWorkers`
- [ ] Worker close only fires when `BASECAMP_WORKER_NAME` is set
- [ ] Errors don't prevent session shutdown
- [ ] `src/index.ts` imports and calls `registerWorkers(pi)`
