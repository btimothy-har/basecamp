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

**Detection:** The parser should auto-detect the source format from entry structure. Pi entries have `type: "message"` with a nested `message.role`. Claude entries have the role as the top-level `type` (`"user"`, `"assistant"`). The detection happens per-line in `_parse_line()`.

**Updated `_parse_line` logic:**
```python
# Pi-specific non-message entry types to skip
_PI_SKIP_TYPES = frozenset({
    "session", "model_change", "thinking_level_change",
    "session_info", "label", "custom", "custom_message",
    "compaction", "branch_summary",
})

# Claude-specific entry types to skip
_CLAUDE_SKIP_TYPES = frozenset({"file-history-snapshot"})

def _parse_line(self, line: bytes) -> ParsedEvent | None:
    data = json.loads(line)
    entry_type = data.get("type")
    if not entry_type:
        return None

    # Pi format: type is "message", role is nested
    if entry_type == "message":
        message = data.get("message", {})
        role = message.get("role")
        if not role:
            return None
        ts_raw = data.get("timestamp")
        if not ts_raw:
            return None
        timestamp = datetime.fromisoformat(ts_raw)
        return ParsedEvent(
            event_type=role,
            timestamp=timestamp,
            content=line.decode("utf-8", errors="replace"),
            message_uuid=data.get("id"),
            source="pi",
        )

    # Pi non-message entries: skip
    if entry_type in _PI_SKIP_TYPES:
        return None

    # Claude format: type IS the role
    if entry_type in _CLAUDE_SKIP_TYPES:
        return None
    ts_raw = data.get("timestamp")
    if not ts_raw:
        return None
    timestamp = datetime.fromisoformat(ts_raw)
    return ParsedEvent(
        event_type=entry_type,
        timestamp=timestamp,
        content=line.decode("utf-8", errors="replace"),
        message_uuid=data.get("uuid"),
        source="claude",
    )
```

### File: `observer/src/observer/pipeline/models.py`

Add `source` field to `ParsedEvent`:
```python
@dataclass(frozen=True, slots=True)
class ParsedEvent:
    event_type: str
    timestamp: datetime
    content: str
    message_uuid: str | None
    source: str = "pi"  # "pi" or "claude"
```

### File: `observer/src/observer/pipeline/models.py`

No changes needed. `ParsedEvent` fields (`event_type`, `timestamp`, `content`, `message_uuid`) are generic enough.

### File: `observer/src/observer/constants.py`

Update extractable event types to include `toolResult`:
```python
EXTRACTABLE_EVENT_TYPES = frozenset({"user", "assistant", "toolResult"})
```

---

## Part 2: RawEvent adaptation (dual-source)

### File: `observer/src/observer/data/raw_event.py`

All content-parsing methods must handle both Claude Code and pi formats, dispatching on `self.source`. The existing Claude Code logic is preserved for historical data reprocessing.

**Design pattern:** Each method that touches format-specific fields uses `self.source` to branch. Private helpers `_is_claude` / `_is_pi` make intent clear.

```python
@property
def _is_pi(self) -> bool:
    return self.source == "pi"
```

### Structural differences by source

| Concern | Claude Code (`source="claude"`) | pi (`source="pi"`) |
|---------|-------------------------------|--------------------|
| Tool call block type | `"tool_use"` | `"toolCall"` |
| Tool call input field | `input` | `arguments` |
| Tool result location | content block in user msg | separate `toolResult` message |
| Tool result ID field | `tool_use_id` (in content block) | `toolCallId` (message-level) |
| Tool result name | not available at message level | `toolName` (message-level) |
| Meta/compact flags | `isMeta`, `isCompactSummary` | not present (filtered at parse time) |

### `_parsed` property

No change — both formats use `data.message.content` nesting.

### Method-by-method changes

Each method below shows the dual-source pattern. Where the logic is identical across sources, no branching is needed.

**`is_extractable()`**
```python
def is_extractable(self) -> bool:
    if self.event_type not in EXTRACTABLE_EVENT_TYPES:
        return False
    message, content, data = self._parsed
    if not message and not content:
        return False

    # Claude-specific filters (pi skips these at parse time)
    if self.source == "claude":
        if data.get("isMeta", False) or data.get("isCompactSummary", False):
            return False

    if self.event_type == "toolResult":
        return True  # pi only — always extractable

    # ... rest of user/assistant logic unchanged
```

**`is_tool_use()`**
```python
def is_tool_use(self) -> bool:
    if self.event_type != "assistant":
        return False
    _, content, _ = self._parsed
    block_type = "toolCall" if self._is_pi else "tool_use"
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == block_type for b in content)
    return False
```

**`is_tool_result()`**
```python
def is_tool_result(self) -> bool:
    if self._is_pi:
        return self.event_type == "toolResult"
    # Claude: tool_result blocks inside user messages
    if self.event_type != "user":
        return False
    _, content, _ = self._parsed
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False
```

**`get_tool_use_ids()`**
```python
def get_tool_use_ids(self) -> frozenset[str]:
    _, content, _ = self._parsed
    block_type = "toolCall" if self._is_pi else "tool_use"
    if isinstance(content, list):
        return frozenset(
            b["id"] for b in content
            if isinstance(b, dict) and b.get("type") == block_type and "id" in b
        )
    return frozenset()
```

**`get_tool_result_ids()`**
```python
def get_tool_result_ids(self) -> frozenset[str]:
    if self._is_pi:
        if self.event_type != "toolResult":
            return frozenset()
        message, _, _ = self._parsed
        tool_call_id = message.get("toolCallId")
        return frozenset({tool_call_id}) if tool_call_id else frozenset()
    # Claude: scan content blocks for tool_use_id
    _, content, _ = self._parsed
    if isinstance(content, list):
        return frozenset(
            b["tool_use_id"] for b in content
            if isinstance(b, dict) and b.get("type") == "tool_result" and "tool_use_id" in b
        )
    return frozenset()
```

**`get_tool_name()`**
```python
def get_tool_name(self) -> str | None:
    message, content, _ = self._parsed
    if self._is_pi and self.event_type == "toolResult":
        return message.get("toolName")
    block_type = "toolCall" if self._is_pi else "tool_use"
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == block_type:
                return b.get("name")
    return None
```

**`get_tool_input()`**
```python
def get_tool_input(self) -> dict | None:
    _, content, _ = self._parsed
    block_type = "toolCall" if self._is_pi else "tool_use"
    input_field = "arguments" if self._is_pi else "input"
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == block_type:
                return b.get(input_field)
    return None
```

**`get_tool_result_content()`**
```python
def get_tool_result_content(self) -> str | None:
    if self._is_pi:
        if self.event_type != "toolResult":
            return None
        _, content, _ = self._parsed
    else:
        # Claude: find first tool_result block in content
        _, content, _ = self._parsed
        # ... existing Claude block-scanning logic ...
        return existing_result

    # pi: content is message-level array of text blocks
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

**`is_thinking()`, `is_agent_text()`, `extract_agent_text()`** — dispatch on block type:
```python
block_type = "toolCall" if self._is_pi else "tool_use"
has_tool_use = any(isinstance(b, dict) and b.get("type") == block_type for b in content)
```

**`extract_thinking_text()`** — No change (both formats use `type: "thinking"`, field `thinking`).

**`extract_user_text()`** — Claude path checks for `tool_result` blocks to skip; pi path doesn't need this since tool results are separate messages. Branch on source.

**`format()` and `brief_description()`** — Use source-aware block type names.

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

**`test_parser.py`** — Add pi-format test fixtures alongside existing Claude fixtures. Existing Claude format tests should continue passing (source auto-detection). New tests verify pi format parsing and that `source` field is set correctly.

New pi-format fixtures:
```json
{"type": "session", "version": 3, "id": "test-uuid", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/tmp"}
{"type": "message", "id": "a1b2c3d4", "parentId": null, "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "user", "content": [{"type": "text", "text": "hello"}], "timestamp": 1234567890}}
{"type": "message", "id": "b2c3d4e5", "parentId": "a1b2c3d4", "timestamp": "2026-01-01T00:00:02Z", "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}], "api": "anthropic-messages", "provider": "anthropic", "model": "claude-sonnet-4-5", "usage": {"input": 10, "output": 5, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 15, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}}, "stopReason": "stop", "timestamp": 1234567891}}
```

New test assertions for pi format:
- `event_type` is the role (`"user"`, `"assistant"`, `"toolResult"`)
- `message_uuid` is the entry `id` (8-char hex)
- `source` is `"pi"`
- Non-message entries should be skipped (verify session header, model_change etc are filtered)

Existing Claude format test assertions should be preserved and updated:
- `source` is `"claude"`
- All existing behavior unchanged

**`test_data.py`** — Add pi-format RawEvent content fixtures. Keep existing Claude fixtures. All content-parsing method tests should run for both sources to verify dual-source dispatch.

**`test_ingestion.py`** — Add pi-format JSONL integration tests alongside existing Claude ones.

**`test_refining.py`** — Add pi-format mock RawEvent content (with `toolCall`/`toolResult`). Verify tool pairing works for both source formats.

**`test_models.py`** — May need updates if it tests content parsing. Add `source` field to test models.

**`test_extraction.py`** — Likely no changes (operates on TranscriptEvent text, not raw content).

**`test_indexing.py`** — No changes (operates on Artifacts).

**`test_search_engine.py`** — No changes.

**`test_scoring.py`** — No changes.

**`test_recall.py`** — No changes.

### Test fixture helper

Create a test utility for building pi-format JSONL entries. Keep existing Claude fixture helpers if any.

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

### Schema migration: add `source` column to `raw_events`

Historical data from Claude Code sessions exists and should remain reprocessable. Add a `source` column to distinguish the two formats.

#### Migration: `observer/src/observer/migrations/m004_add_source_column.py`

```python
"""Migration 004: Add source column to raw_events.

Distinguishes between Claude Code and pi transcript formats so
content-parsing methods can dispatch to the correct field names.
Existing rows default to 'claude'.
"""

from sqlalchemy import Engine, text
from observer.services.migrations import migration


@migration(version=4, description="Add source column to raw_events")
def run(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("ALTER TABLE raw_events ADD COLUMN source TEXT NOT NULL DEFAULT 'claude'")
        )
```

#### Register in `observer/src/observer/migrations/__init__.py`

Add:
```python
from observer.migrations import m004_add_source_column as m004_add_source_column
```

#### Schema: `observer/src/observer/data/schemas.py`

Add to `RawEventSchema`:
```python
source: Mapped[str] = mapped_column(String, nullable=False, default="pi")
```

Note: the schema default is `"pi"` (new rows), while the migration default is `"claude"` (existing rows).

#### Domain model: `observer/src/observer/data/raw_event.py`

Add to `RawEvent` Pydantic model:
```python
source: str = "pi"
```

#### Enum: `observer/src/observer/data/enums.py`

Add:
```python
class TranscriptSource(StrEnum):
    CLAUDE = "claude"
    PI = "pi"
```

---

## Execution order

1. **Migration** — Create `m004_add_source_column.py`, register in `__init__.py`, add `source` field to schema and domain model
2. **Enums** — Add `TranscriptSource` enum
3. **ParsedEvent** — Add `source` field
4. **Parser + constants** — Add pi skip types, update `_parse_line()` with auto-detection, update `EXTRACTABLE_EVENT_TYPES`, pass `source` through to RawEvent in `ingest()`
5. **RawEvent** — Add `_is_pi` property, adapt all content-parsing methods with dual-source dispatch (preserve all existing Claude logic)
6. **Grouper** — Verify tool pairing works for both sources (should need no changes if RawEvent methods dispatch correctly)
7. **Test fixtures** — Create pi-format fixture helpers, add pi-format tests alongside existing Claude tests
8. **Run tests** — `uv run pytest observer/tests/ -x` — all existing Claude tests must still pass, new pi tests must pass
9. **Pi extension** — Create `plugins/observer/` with hooks and commands
10. **Registration** — Verify works with pi session paths (likely no code changes)
11. **Companion cleanup** — Remove migrated shell scripts and hook entries
12. **Constants cleanup** — Remove Claude Code path constants
13. **Lint + format** — `uv run ruff check observer/ && uv run ruff format observer/`
