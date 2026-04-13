# 03 — Port Session Lifecycle & Project Context

## Goal

Migrate session initialization (env vars, scratch dirs) from `pi-eng/extension/index.ts` and project context injection from `companion/scripts/project-context.sh` + `companion/scripts/session-init.sh`.

## Sources

### 1. `plugins/pi-eng/extension/index.ts` — `session_start` handler

Sets up:
- `GIT_REPO` env var (via `git rev-parse --show-toplevel`, fallback to `path.basename(cwd)`)
- Scratch directories: `$BASECAMP_SCRATCH_DIR/pull_requests/` and `$BASECAMP_SCRATCH_DIR/pr-comments/`
- Notification of repo name and scratch path

### 2. `plugins/companion/scripts/session-init.sh`

Reads `session_id` and `transcript_path` from Claude Code's SessionStart hook stdin JSON. Writes them to `$CLAUDE_ENV_FILE` so subsequent bash calls can access them.

**In pi:** There is no `$CLAUDE_ENV_FILE` mechanism. Pi extensions have direct access to the session via `ctx.sessionManager`. Session ID is available from `ctx.sessionManager.getSessionFile()`. The transcript path concept doesn't exist in pi (sessions are JSONL files managed by pi itself). This script's behavior is **mostly unnecessary** — but if `BASECAMP_INBOX_DIR` needs to be derived from session ID for worker messaging, compute it in the `session_start` handler and set it on `process.env`.

### 3. `plugins/companion/scripts/project-context.sh`

Reads `$BASECAMP_CONTEXT_FILE`, cats the file, and outputs JSON to inject `additionalContext` at session start.

**In pi:** Use `before_agent_start` to return a `{ message }` with the context content. This places it in the conversation alongside CLAUDE.md rather than in the system prompt.

## Target

**File:** `extension/src/lifecycle.ts`

Export:

```typescript
export function registerLifecycle(pi: ExtensionAPI): void
```

### `session_start` handler

```typescript
pi.on("session_start", async (_event, ctx) => {
  // 1. Determine git repo name
  let gitRepo: string;
  try {
    const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd: ctx.cwd });
    gitRepo = path.basename(result.stdout.trim());
  } catch {
    gitRepo = path.basename(ctx.cwd);
  }
  process.env.GIT_REPO = gitRepo;

  // 2. Create scratch directories
  const scratch = process.env.BASECAMP_SCRATCH_DIR || `/tmp/claude-workspace/${gitRepo}`;
  await fs.mkdir(path.join(scratch, "pull_requests"), { recursive: true });
  await fs.mkdir(path.join(scratch, "pr-comments"), { recursive: true });

  // 3. Set up inbox directory keyed by session
  const sessionFile = ctx.sessionManager.getSessionFile();
  if (sessionFile) {
    const sessionId = path.basename(sessionFile, path.extname(sessionFile));
    const inboxDir = `/tmp/claude-workspace/inbox/${sessionId}`;
    await fs.mkdir(inboxDir, { recursive: true });
    process.env.BASECAMP_INBOX_DIR = inboxDir;
  }

  ctx.ui.notify(`basecamp: repo=${gitRepo}`, "info");
});
```

### `before_agent_start` handler — project context injection

```typescript
pi.on("before_agent_start", async (_event, _ctx) => {
  const contextFile = process.env.BASECAMP_CONTEXT_FILE;
  if (!contextFile) return;

  try {
    const content = await fs.readFile(contextFile, "utf8");
    return {
      message: {
        customType: "basecamp-context",
        content,
        display: true,
      },
    };
  } catch {
    // File missing or unreadable — skip silently
  }
});
```

### Update `src/index.ts`

Uncomment the lifecycle import and registration call.

## Design Decisions

- `GIT_REPO` is set on `process.env` so skills and bash commands can read it (backward compat with existing skills that reference it)
- `BASECAMP_INBOX_DIR` is derived from pi's session file path rather than Claude's session_id — functionally equivalent for inbox routing
- Project context is injected via `before_agent_start` message, not system prompt modification — this is intentional per the architecture decision in CLAUDE.md
- The `before_agent_start` handler fires on **every** user prompt, but the message is only injected once because pi deduplicates by `customType` — verify this behavior. If pi doesn't deduplicate, add a guard flag (`let contextInjected = false`)

## Acceptance Criteria

- [ ] `extension/src/lifecycle.ts` exists and exports `registerLifecycle`
- [ ] `session_start` creates scratch dirs and sets env vars
- [ ] `before_agent_start` injects project context file content as a message
- [ ] `src/index.ts` imports and calls `registerLifecycle(pi)`
- [ ] Test: launch with `BASECAMP_SCRATCH_DIR` set — dirs created
- [ ] Test: launch with `BASECAMP_CONTEXT_FILE` pointing to a real file — content appears in conversation
