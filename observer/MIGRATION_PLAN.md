# Observer Migration Plan: Claude Code → pi

## Overview

Migrate the observer pipeline from Claude Code's transcript format to pi's session format, and replace the companion plugin's shell-script hooks with a pi extension.

### Already completed
- Replaced `Agent` class (`claude -p` subprocess) with pydantic-ai for LLM calls
- Config stores `provider:model` format (e.g. `anthropic:claude-sonnet-4-20250514`)
- Dropped `questionary` dependency
- Refinement pipeline converted to async with semaphore-based concurrency

### Remaining work
1. Adapt parser and RawEvent for pi's JSONL format
2. Adapt grouper for pi's message structure
3. Build pi extension (hooks + commands + skill)
4. Update registration for pi session paths
5. Update tests
6. Clean up dead code

---

## Part 1: Parser adaptation

### File: `observer/src/observer/pipeline/parser.py`

**Current behavior:** Reads JSONL from byte offset. Each line has top-level `type` field that equals the message role (`"user"`, `"assistant"`). Stores the role as `event_type` and `uuid` as `message_uuid`.

**Pi format differences:**
- Session header (first line): `{"type": "session", "version": 3, "id": "uuid", "timestamp": "...", "cwd": "..."}`
- Non-message entries: `model_change`, `thinking_level_change`, `session_info`, `label`, `custom`, `custom_message`, `compaction`, `branch_summary` — all should be **skipped**
- Message entries: `{"type": "message", "id": "8-char-hex", "parentId": "...", "timestamp": "ISO", "message": {"role": "...", "content": [...]}}`
- The message `role` is the event type: `"user"`, `"assistant"`, `"toolResult"`
- Entry-level `id` field (8-char hex), not `uuid`
- Entry-level `timestamp` is ISO string (same as before)

**Changes:**
1. Update `_SKIP_TYPES` to skip all non-message entry types:
   ```python
   _SKIP_TYPES = frozenset({
       "session", "model_change", "thinking_level_change",
       "session_info", "label", "custom", "custom_message",
       "compaction", "branch_summary",
   })
   ```
2. In `_parse_line()`:
   - After parsing JSON: if `type` is in `_SKIP_TYPES`, return None
   - If `type == "message"`: extract `message.role` as `event_type`
   - Use entry-level `id` for `message_uuid` (not `uuid`)
   - Use entry-level `timestamp` (unchanged)

**Updated `_parse_line` logic:**
```python
def _parse_line(self, line: bytes) -> ParsedEvent | None:
    data = json.loads(line)
    entry_type = data.get("type")
    
    if not entry_type or entry_type in _SKIP_TYPES:
        return None
    
    if entry_type != "message":
        return None  # unknown entry type, skip
    
    message = data.get("message", {})
    role = message.get("role")
    if not role:
        return None
    
    ts_raw = data.get("timestamp")  # entry-level, ISO string
    timestamp = datetime.fromisoformat(ts_raw)
    
    return ParsedEvent(
        event_type=role,  # "user", "assistant", "toolResult"
        timestamp=timestamp,
        content=line.decode("utf-8", errors="replace"),
        message_uuid=data.get("id"),  # 8-char hex entry ID
    )
```

### File: `observer/src/observer/pipeline/models.py`

No changes needed. `ParsedEvent` fields (`event_type`, `timestamp`, `content`, `message_uuid`) are generic enough.

### File: `observer/src/observer/constants.py`

Update extractable event types to include `toolResult`:
```python
EXTRACTABLE_EVENT_TYPES = frozenset({"user", "assistant", "toolResult"})
```

---

## Part 2: RawEvent adaptation

### File: `observer/src/observer/data/raw_event.py`

The `_parsed` property and all content-parsing methods need updating for pi's field names and structure.

**Structural difference — tool results:**
- Claude Code: tool results are content blocks (`type: "tool_result"`) inside user messages
- Pi: tool results are separate messages with `role: "toolResult"`, with `toolCallId` and `toolName` at the message level, and `content` as a top-level array of text blocks

**Structural difference — tool calls:**
- Claude Code: `type: "tool_use"`, `id`, `name`, `input`
- Pi: `type: "toolCall"`, `id`, `name`, `arguments`

### `_parsed` property

Current: `data.get("message", {})` then `message.get("content", "")`

For pi, the JSON structure is:
```json
{
  "type": "message",
  "id": "abc123",
  "parentId": "def456",
  "timestamp": "2026-...",
  "message": {
    "role": "user|assistant|toolResult",
    "content": [...],
    // assistant-only: "api", "provider", "model", "usage", "stopReason"
    // toolResult-only: "toolCallId", "toolName", "isError"
  }
}
```

The `_parsed` property should return `(message_dict, content, raw_data)` — same shape, just the nesting is compatible. **No change needed** to `_parsed` itself.

### Method-by-method changes

**`is_user_prompt()`** — No change (checks `event_type == "user"` + `is_extractable()`)

**`is_extractable()`** — Add `"toolResult"` handling:
```python
if self.event_type == "toolResult":
    return True  # always extractable (content is tool output)
```
Remove `isMeta` and `isCompactSummary` checks (don't exist in pi).

**`is_tool_use()`** — Change content block type check:
```python
# Old: block.get("type") == "tool_use"
# New: block.get("type") == "toolCall"
```

**`is_tool_result()`** — Complete rewrite. No longer checks content blocks:
```python
def is_tool_result(self) -> bool:
    return self.event_type == "toolResult"
```

**`get_tool_use_id()` / `get_tool_use_ids()`** — Change block type filter:
```python
# Old: block.get("type") == "tool_use"
# New: block.get("type") == "toolCall"
```
The `id` field name is the same in both formats.

**`get_tool_result_id()` / `get_tool_result_ids()`** — Read from message level, not content blocks:
```python
def get_tool_result_ids(self) -> frozenset[str]:
    if self.event_type != "toolResult":
        return frozenset()
    message, _, _ = self._parsed
    tool_call_id = message.get("toolCallId")
    return frozenset({tool_call_id}) if tool_call_id else frozenset()
```

**`get_tool_name()`** — Two paths:
```python
def get_tool_name(self) -> str | None:
    message, content, _ = self._parsed
    # toolResult messages: name at message level
    if self.event_type == "toolResult":
        return message.get("toolName")
    # assistant messages: name in toolCall blocks
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "toolCall":
                return b.get("name")
    return None
```

**`get_tool_input()`** — Change field name:
```python
# Old: block.get("input")
# New: block.get("arguments")
```

**`get_tool_result_content()`** — Read from message-level content array:
```python
def get_tool_result_content(self) -> str | None:
    if self.event_type != "toolResult":
        return None
    _, content, _ = self._parsed
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else None
    return None
```

**`extract_user_text()`** — No change (already handles string and list content)

**`extract_agent_text()`** — Change `"tool_use"` to `"toolCall"`:
```python
# Old: block.get("type") == "tool_use"
# New: block.get("type") == "toolCall"
```

**`extract_thinking_text()`** — No change (pi uses same `type: "thinking"` and `thinking` field)

**`is_thinking()`** — Change `"tool_use"` to `"toolCall"`:
```python
has_tool_use = any(isinstance(b, dict) and b.get("type") == "toolCall" for b in content)
```

**`is_agent_text()`** — Change `"tool_use"` to `"toolCall"`:
```python
has_tool_use = any(isinstance(b, dict) and b.get("type") == "toolCall" for b in content)
```

**`format()` and `brief_description()`** — Update content block type references from `"tool_use"` → `"toolCall"` and `"tool_result"` → `"toolResult"` (or remove tool_result handling since those are now separate messages).

**Methods to remove or simplify:**
- The `is_tool_result` content-block scanning path inside user messages is dead — tool results are never inside user messages in pi. Remove the `"tool_result"` content block handling from `is_extractable()`, `extract_user_text()`, and `brief_description()`.

---

## Part 3: Grouper adaptation

### File: `observer/src/observer/pipeline/refining/grouping.py`

**Current behavior:** `classify_events` iterates raw events and:
- User text → `PROMPT`
- Assistant with `tool_use` blocks → tracks in `pending_tool_uses` dict, waits for matching `tool_result`
- User with `tool_result` blocks → matches against pending tool uses → `TOOL_PAIR`
- Unmatched tool results → `ORPHANED_RESULT`
- Assistant thinking-only → `THINKING`
- Assistant text-only → `RESPONSE`

**Pi structural change:** Tool results are separate `toolResult` messages, not content blocks inside user messages. The pairing logic simplifies:

```python
def classify_events(events: list[RawEvent]) -> list[ClassifiedItem]:
    items: list[ClassifiedItem] = []
    pending_tool_uses: dict[str, RawEvent] = {}

    for event in events:
        if event.is_user_prompt():
            items.append(ClassifiedItem(WorkItemType.PROMPT, [event]))

        elif event.is_tool_use():
            if event.get_tool_name() in SKIP_TOOLS:
                items.append(ClassifiedItem(WorkItemType.TASK_MANAGEMENT, [event]))
            else:
                for tool_id in event.get_tool_use_ids():
                    pending_tool_uses[tool_id] = event

        elif event.is_tool_result():
            # Pi: toolResult is a separate message with toolCallId
            matched = False
            for result_id in event.get_tool_result_ids():
                if result_id in pending_tool_uses:
                    use_event = pending_tool_uses.pop(result_id)
                    items.append(ClassifiedItem(WorkItemType.TOOL_PAIR, [use_event, event]))
                    matched = True
                    break
            if not matched:
                items.append(ClassifiedItem(WorkItemType.ORPHANED_RESULT, [event]))

        elif event.is_thinking():
            # ... unchanged
        elif event.is_agent_text():
            # ... unchanged
        else:
            items.append(ClassifiedItem(WorkItemType.UNRECOGNIZED, [event]))

    return items
```

The logic is actually almost identical — the only real difference is that `is_tool_result()` now matches on `event_type == "toolResult"` instead of scanning content blocks. The pairing via `get_tool_result_ids()` → `pending_tool_uses` still works the same way.

**SKIP_TOOLS update:** Review whether pi uses the same tool names. Pi's built-in tools don't include TaskCreate/TaskUpdate/TaskList/TaskGet (those were Claude Code specific). Remove or update `SKIP_TOOLS` based on what pi's extensions register. For now, keep the set but it may produce no matches.

---

## Part 4: Pi extension

### Location: `plugins/observer/` (new pi extension)

This replaces the shell scripts in `plugins/companion/` that handled observer hooks. The companion plugin's observer-related scripts (`hook-process.sh`, `pretool-ingest.sh`, `session-init.sh`, `session-close.sh`) should be removed after migration.

### File structure
```
plugins/observer/
├── index.ts                # Extension entry point
├── package.json            # Dependencies (if any)
└── skills/
    └── recall/
        └── SKILL.md        # Recall skill (move from companion)
```

### Extension: `index.ts`

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

export default function (pi: ExtensionAPI) {
    // --- Session lifecycle hooks ---

    pi.on("session_start", async (event, ctx) => {
        // Expose session metadata for observer CLI access.
        // Pi doesn't have CLAUDE_ENV_FILE, but we can set env vars
        // for bash tool calls via other means, or pass session info
        // directly when invoking observer.
    });

    pi.on("session_shutdown", async (_event, ctx) => {
        // Trigger observer ingest + process on session end.
        // Build the hook input JSON that observer ingest expects.
        const sessionFile = ctx.sessionManager.getSessionFile();
        const sessionId = ctx.sessionManager.getSessionId();
        const cwd = ctx.cwd;

        if (!sessionFile || !sessionId) return;

        const hookInput = JSON.stringify({
            session_id: sessionId,
            transcript_path: sessionFile,
            cwd: cwd,
        });

        // Background: ingest + process (detached, non-blocking)
        await pi.exec("bash", ["-c",
            `echo '${hookInput.replace(/'/g, "'\\''")}' | nohup observer ingest --process >/dev/null 2>&1 &`
        ]);
    });

    pi.on("session_before_compact", async (_event, ctx) => {
        // Trigger observer ingest before compaction discards context.
        const sessionFile = ctx.sessionManager.getSessionFile();
        const sessionId = ctx.sessionManager.getSessionId();
        const cwd = ctx.cwd;

        if (!sessionFile || !sessionId) return;

        const hookInput = JSON.stringify({
            session_id: sessionId,
            transcript_path: sessionFile,
            cwd: cwd,
        });

        await pi.exec("bash", ["-c",
            `echo '${hookInput.replace(/'/g, "'\\''")}' | nohup observer ingest --process >/dev/null 2>&1 &`
        ]);
    });

    // --- Extension commands ---

    pi.registerCommand("observer-setup", {
        description: "Configure observer models and mode",
        handler: async (args, ctx) => {
            if (!ctx.hasUI) return;

            // Show current config
            const { stdout: current } = await pi.exec("observer", ["setup"]);
            ctx.ui.notify(current, "info");

            // Interactive model selection
            const extractionModel = await ctx.ui.input(
                "Extraction model",
                "pydantic-ai model string (e.g. anthropic:claude-sonnet-4-20250514)"
            );
            if (!extractionModel) return;

            const summaryModel = await ctx.ui.input(
                "Summary model",
                "pydantic-ai model string (e.g. anthropic:claude-3-5-haiku-latest)"
            );
            if (!summaryModel) return;

            const mode = await ctx.ui.select(
                "Processing mode",
                ["on", "off"]
            );
            if (!mode) return;

            await pi.exec("observer", [
                "setup",
                "-e", extractionModel,
                "-s", summaryModel,
                "-m", mode,
            ]);

            ctx.ui.notify("Observer configuration updated", "success");
        },
    });

    pi.registerCommand("observer-status", {
        description: "Show observer database status",
        handler: async (_args, ctx) => {
            const { stdout } = await pi.exec("observer", ["db", "status"]);
            if (ctx.hasUI) {
                ctx.ui.notify(stdout, "info");
            }
        },
    });

    pi.registerCommand("observer-mode", {
        description: "Toggle observer processing mode (on/off)",
        handler: async (args, ctx) => {
            if (args) {
                await pi.exec("observer", ["mode", args.trim()]);
            }
            const { stdout } = await pi.exec("observer", ["mode"]);
            if (ctx.hasUI) {
                ctx.ui.notify(stdout, "info");
            }
        },
    });
}
```

### Skill: `plugins/observer/skills/recall/SKILL.md`

Move from `plugins/companion/skills/recall/SKILL.md` — content unchanged. The `recall` CLI remains the interface.

### Registration in pi

Add to `~/.pi/agent/extensions/` or project `.pi/extensions/` as appropriate. Or register via settings.json `extensions` array.

---

## Part 5: Registration updates

### File: `observer/src/observer/services/registration.py`

**Current:** `HookInput` expects `session_id`, `transcript_path`, `cwd`. The `transcript_path` pointed to Claude Code's transcript file (`~/.claude/projects/.../transcript.jsonl`).

**Pi change:** `transcript_path` now points to pi's session file (`~/.pi/agent/sessions/--encoded-cwd--/timestamp_uuid.jsonl`). No code change needed — the path is opaque to registration, it just stores it for the parser to read later.

**Session ID:** Pi's session ID is a full UUID (e.g. `8411bf97-e400-4205-b2cf-4e47b2561808`). Claude Code also used UUIDs. No change needed.

**Worktree detection:** The `detect_worktree()` function checks if cwd is under `~/.worktrees/`. This is basecamp-specific and still works with pi. No change needed.

---

## Part 6: Test updates

### Tests that need updating for pi format

**`test_parser.py`** — Rewrite test JSONL fixtures to use pi's format:
```json
{"type": "session", "version": 3, "id": "test-uuid", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/tmp"}
{"type": "message", "id": "a1b2c3d4", "parentId": null, "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "user", "content": [{"type": "text", "text": "hello"}], "timestamp": 1234567890}}
{"type": "message", "id": "b2c3d4e5", "parentId": "a1b2c3d4", "timestamp": "2026-01-01T00:00:02Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}], "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5", "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}, "stopReason": "stop", "timestamp": 1234567891}}
```

Update test assertions:
- `event_type` is now the role (`"user"`, `"assistant"`, `"toolResult"`) not the entry type
- `message_uuid` is the entry `id` (8-char hex)
- Non-message entries should be skipped (verify session header, model_change etc are filtered)

**`test_data.py`** — Update RawEvent content fixtures to pi's JSON structure. All content-parsing method tests need pi-format JSON.

**`test_ingestion.py`** — Update JSONL fixtures used in integration tests.

**`test_refining.py`** — Update mock RawEvent content to use `toolCall`/`toolResult` format. Tool pairing tests should use separate `toolResult` messages.

**`test_models.py`** — May need updates if it tests content parsing.

**`test_extraction.py`** — Likely no changes (operates on TranscriptEvent text, not raw content).

**`test_indexing.py`** — No changes (operates on Artifacts).

**`test_search_engine.py`** — No changes.

**`test_scoring.py`** — No changes.

**`test_recall.py`** — No changes.

### Test fixture helper

Create a test utility for building pi-format JSONL entries:

```python
# observer/tests/conftest.py or observer/tests/fixtures.py

def make_session_header(session_id="test-session", cwd="/tmp/test"):
    return json.dumps({
        "type": "session", "version": 3,
        "id": session_id, "timestamp": "2026-01-01T00:00:00Z", "cwd": cwd,
    })

def make_user_message(text, entry_id="a1b2c3d4", parent_id=None, timestamp="2026-01-01T00:00:01Z"):
    return json.dumps({
        "type": "message", "id": entry_id, "parentId": parent_id,
        "timestamp": timestamp,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
            "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
        },
    })

def make_assistant_message(text=None, tool_calls=None, thinking=None,
                           entry_id="b2c3d4e5", parent_id="a1b2c3d4",
                           timestamp="2026-01-01T00:00:02Z"):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": thinking})
    if text:
        content.append({"type": "text", "text": text})
    if tool_calls:
        for tc in tool_calls:
            content.append({
                "type": "toolCall", "id": tc["id"],
                "name": tc["name"], "arguments": tc.get("arguments", {}),
            })
    return json.dumps({
        "type": "message", "id": entry_id, "parentId": parent_id,
        "timestamp": timestamp,
        "message": {
            "role": "assistant", "content": content,
            "api": "anthropic-messages", "provider": "anthropic",
            "model": "claude-sonnet-4-5",
            "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0,
                      "totalTokens": 0, "cost": {"input": 0, "output": 0,
                      "cacheRead": 0, "cacheWrite": 0, "total": 0}},
            "stopReason": "toolUse" if tool_calls else "stop",
            "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
        },
    })

def make_tool_result(tool_call_id, tool_name, content_text, is_error=False,
                     entry_id="c3d4e5f6", parent_id="b2c3d4e5",
                     timestamp="2026-01-01T00:00:03Z"):
    return json.dumps({
        "type": "message", "id": entry_id, "parentId": parent_id,
        "timestamp": timestamp,
        "message": {
            "role": "toolResult",
            "toolCallId": tool_call_id,
            "toolName": tool_name,
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error,
            "timestamp": int(datetime.fromisoformat(timestamp).timestamp() * 1000),
        },
    })
```

---

## Part 7: Cleanup

### Files/code to remove from companion plugin

After the pi extension is functional:
- `plugins/companion/scripts/hook-process.sh` — replaced by extension `session_shutdown` and `session_before_compact` hooks
- `plugins/companion/scripts/pretool-ingest.sh` — replaced by extension hook (if dispatch pre-ingest is still needed)
- `plugins/companion/scripts/session-init.sh` — replaced by extension `session_start` hook
- `plugins/companion/scripts/session-close.sh` — not observer-related (worker close), leave as-is or migrate separately
- `plugins/companion/skills/recall/SKILL.md` — move to `plugins/observer/skills/recall/`
- Update `plugins/companion/hooks/hooks.json` to remove observer-related hook entries

### Constants cleanup

In `observer/src/observer/constants.py`:
- Remove `CLAUDE_DIR` and `PROJECTS_DIR` (Claude Code paths, no longer used)
- Keep `BASECAMP_DIR`, `OBSERVER_DIR`, `DB_PATH`, etc.

### No schema migration needed

The RawEvent table schema doesn't change — `event_type`, `timestamp`, `content`, `message_uuid` all remain. Only the values stored in these fields change (e.g. `event_type` now stores `"toolResult"` instead of never storing it). Existing data from Claude Code sessions will have the old format but won't be re-ingested.

If a clean break is desired, run `observer db reset` to start fresh.

---

## Execution order

1. **Parser + constants** — Update `_SKIP_TYPES`, `EXTRACTABLE_EVENT_TYPES`, and `_parse_line()` for pi format
2. **RawEvent** — Adapt all content-parsing methods for pi's field names
3. **Grouper** — Verify/adapt tool pairing logic (should be minimal)
4. **Test fixtures** — Create pi-format fixture helpers, update all test files
5. **Run tests** — `uv run pytest observer/tests/ -x` until green
6. **Pi extension** — Create `plugins/observer/` with hooks and commands
7. **Registration** — Verify works with pi session paths (likely no code changes)
8. **Companion cleanup** — Remove migrated shell scripts and hook entries
9. **Constants cleanup** — Remove Claude Code path constants
10. **Lint + format** — `uv run ruff check observer/ && uv run ruff format observer/`
