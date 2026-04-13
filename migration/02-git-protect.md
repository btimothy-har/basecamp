# 02 — Port Git Protection

## Goal

Migrate `plugins/pi-git-protect/index.ts` into `extension/src/git-protect.ts`. This is the simplest migration — pure logic, no external dependencies, no state.

## Source

**File:** `plugins/pi-git-protect/index.ts`

**Behavior:** Subscribes to `tool_call` events for bash commands and blocks:
- `git push --force` / `--force-with-lease` / `-f`
- `git push --delete` or colon-prefix ref deletion (`:ref`)
- `git clean -f` / `--force`
- Destructive `gh` commands (allows: `gh issue *`, read-only `gh pr/run/repo` subcommands, `gh search`, `gh browse`)

There's also an `isIdempotentMkdir` function that checks if all mkdir targets already exist — this was used in the Claude Code plugin for auto-approval but has no effect in pi (pi's `tool_call` can only block, not auto-allow). **Drop this function.**

## Target

**File:** `extension/src/git-protect.ts`

Export a single function:

```typescript
export function registerGitProtect(pi: ExtensionAPI): void
```

### Implementation Notes

- Copy all the guard functions (`isForcePush`, `isRemoteRefDelete`, `isForceClean`, `getGhBlockReason`, `checkCommand`) as-is — they're pure string logic, well-tested
- Remove `isIdempotentMkdir` — no equivalent in pi's event model
- Remove the `statSync` import (only used by mkdir check)
- Use `isToolCallEventType("bash", event)` for type narrowing
- The handler returns `{ block: true, reason }` when a command should be blocked

### Update `src/index.ts`

Uncomment the git-protect import and registration call.

## Acceptance Criteria

- [ ] `extension/src/git-protect.ts` exists and exports `registerGitProtect`
- [ ] All git/gh guard logic preserved (minus mkdir auto-approve)
- [ ] `src/index.ts` imports and calls `registerGitProtect(pi)`
- [ ] Test: `pi -e ./extension` then ask it to run `git push --force` — should be blocked
- [ ] Test: `gh issue list` should NOT be blocked
- [ ] Test: `gh pr merge` should be blocked
