# Basecamp → pi-coding-agent Migration Plan

## Executive Summary

Basecamp is a Python CLI that wraps the `claude` CLI with project configuration, system prompt assembly, worktree management, worker dispatch, and plugin support. Pi-coding-agent is a TypeScript coding harness with native support for extensions, skills, prompt templates, packages, and multi-provider model selection.

**Goal**: Replace the `claude` CLI execution backend with `pi` while maintaining full feature parity from the user's perspective.

---

## Current Architecture (Basecamp)

### What basecamp-core does

| Layer | Current Implementation | CLI Entry |
|-------|----------------------|-----------|
| **Project Config** | `~/.basecamp/config.json` → `ProjectConfig` (dirs, working_style, context) | `basecamp project add/edit/list/remove` |
| **System Prompt Assembly** | Layered: runtime preamble → environment.md → working style → system.md | Automatic on launch |
| **Claude Launch** | `execvp("claude", [...flags])` with `--system-prompt`, `--settings`, `--add-dir`, `--plugin-dir` | `basecamp claude <project>` |
| **Settings Mutation** | Reads `~/.claude/settings.json`, strips apiKeyHelper, merges .env + BASECAMP_* vars, writes cached settings file | Automatic on launch |
| **Worktree Management** | Git worktrees in `~/.worktrees/<repo>/<label>/` with `.meta/` JSON | `basecamp worktree list/clean` |
| **Worker Dispatch** | Creates `launch.sh` scripts, spawns tmux/Kitty panes via backend | `basecamp worker create/dispatch/list` |
| **Plugins** | Claude Code `.claude-plugin` format (plugin.json + hooks.json + shell scripts) | `--plugin-dir` flag at launch |
| **Companion Plugin** | SessionStart → session-id capture + context injection; Stop → inbox check; PreCompact/SessionEnd → observer ingest | Always bundled |
| **Terminal Backends** | TmuxBackend, KittyBackend, DirectBackend (execvp) | Auto-detected |

### What the plugins do

| Plugin | Hooks | Purpose |
|--------|-------|---------|
| **bc-companion** (bundled) | SessionStart, Stop, PostToolUse, PreToolUse, PreCompact, SessionEnd | Session ID export, context injection, inbox check, observer ingest |
| **bc-eng** | SessionStart, UserPromptSubmit, PreToolUse | Skill/agent reminders on prompt and before edits |
| **bc-git-protect** | PreToolUse (Bash), PermissionRequest (Bash) | Block destructive git/gh operations |
| **bc-collab** | (marketplace) | Discovery skill, gh-issue skill, issue-worker agent |
| **bc-gpg-check** | PreToolUse | GPG card verification |
| **bc-cursor** | SessionStart | .cursor context file discovery |

### Observer integration

- `observer ingest` called by companion hooks on SessionEnd and PreCompact
- `recall` CLI used as a skill inside sessions
- Agent class wraps `claude -p` subprocess for LLM extraction → **must change to `pi -p`**

---

## pi-coding-agent Capabilities (Target)

### What pi provides natively (no extension needed)

| Basecamp Feature | pi Native Equivalent |
|-------------------|---------------------|
| `--system-prompt` | `--system-prompt` or `.pi/SYSTEM.md` / `~/.pi/agent/SYSTEM.md` |
| `--add-dir` | Context files (`AGENTS.md`) walk parent dirs; skills can reference any path |
| Settings mutation | `~/.pi/agent/settings.json` + `.pi/settings.json` with project overrides |
| `.env` merging | `settings.json` `env` field, or extension `before_agent_start` |
| Working styles | Prompt templates (`~/.pi/agent/prompts/*.md`) or `APPEND_SYSTEM.md` |
| Project context injection | `AGENTS.md` / `CLAUDE.md` auto-discovery, or extension `before_agent_start` |
| Session resume | `-c`, `-r`, `--session` |
| Model selection | `--model`, `--provider`, `/model`, Ctrl+P cycling |
| Thinking levels | `--thinking`, Shift+Tab cycling |
| Session branching | `/tree`, `/fork` |
| Compaction | `/compact`, auto-compaction |
| Plugin system | Extensions (TypeScript) + Skills (Markdown) + Pi Packages |
| Worker dispatch | **Not built-in** — pi explicitly leaves this to extensions/tmux |
| Git worktree management | **Not built-in** — filesystem concern outside pi's scope |
| Terminal multiplexer | **Not built-in** — pi philosophy: use tmux directly |
| Observer ingest hooks | **Not built-in** — extension events provide the hooks |

### What pi extensions provide

| Basecamp Feature | pi Extension Equivalent |
|-------------------|------------------------|
| SessionStart hook (session-id capture) | `session_start` event — `ctx.sessionManager.getSessionFile()` / `session_id` |
| Context injection via BASECAMP_CONTEXT_FILE | `before_agent_start` event → return `{ message: ... }` |
| PreToolUse guard (git protect) | `tool_call` event → `return { block: true }` |
| PostToolUse inbox check | `tool_result` event or `tool_execution_end` |
| PreCompact/SessionEnd observer ingest | `session_before_compact` / `session_shutdown` events |
| Worker dispatch | Custom tool registered via `pi.registerTool()` |
| GPG check | `tool_call` event with bash command filtering |
| .cursor context discovery | `resources_discover` event → return context file paths |

---

## Feature Parity Mapping

### ✅ Direct Replacements (pi does it natively)

1. **System prompt assembly** → `.pi/SYSTEM.md` (project) or `--system-prompt` flag
2. **Environment/context info in prompt** → `AGENTS.md` auto-loading + `before_agent_start` extension
3. **Working styles** → Prompt templates (`/engineering`, `/advisor`)
4. **Session resume/continue** → `-c`, `-r` built-in
5. **Model selection** → `--model`, `/model`, Ctrl+P
6. **Settings management** → `settings.json` with project overrides
7. **.env merging** → Extension reads `.env` and injects via `before_agent_start` message

### 🔄 Requires Extension (pi doesn't do it, but extension API covers it)

8. **Session ID capture + env export** → `session_start` event (session ID available directly on context)
9. **Project context injection (BASECAMP_CONTEXT_FILE)** → `before_agent_start` injects message
10. **Worker dispatch** → Custom `dispatch` tool + bash spawning pi in tmux pane
11. **Git protection (force push, clean, etc.)** → `tool_call` event blocks dangerous bash commands
12. **Observer ingest on PreCompact/SessionEnd** → `session_before_compact` + `session_shutdown` events
13. **Inbox checking** → `tool_execution_end` event or polling in extension
14. **GPG card verification** → `tool_call` event filtering
15. **Cursor context discovery** → `resources_discover` event returns additional context files
16. **Engineering skill/agent reminders** → `input` event transformation or `tool_call` event

### 🔧 Requires CLI Wrapper (pi can't do it from inside)

17. **Project config management** → Keep basecamp CLI for `basecamp project add/edit/list/remove`
18. **Worktree management** → Keep basecamp CLI for `basecamp worktree list/clean`
19. **Launch orchestration** → `basecamp pi <project>` replaces `basecamp claude <project>`
20. **Logseq journal/reflect/plan** → Keep as basecamp CLI commands (not pi concerns)

---

## Migration Plan

### Phase 0: Restructure (No feature changes)

**Goal**: Reorganize the repo to accommodate both backends during transition.

1. **Create `core/src/core/launchers/` directory** — abstraction over the CLI backend
   - `base.py` — `Launcher` protocol: `assemble_prompt()`, `build_settings()`, `exec_session()`
   - `claude.py` — current behavior extracted from `launch.py`
   - `pi.py` — new pi backend (initially empty/stub)

2. **Make `execute_launch()` delegate to a launcher**
   - `resolve_launcher("claude" | "pi")` based on config or CLI flag
   - All current tests still pass — no behavior change

3. **Add `--launcher` flag to `basecamp claude`**
   - Default: `"claude"` (existing behavior)
   - `basecamp claude myproject --launcher pi` for testing

### Phase 1: Core Launch (pi replaces claude CLI)

**Goal**: `basecamp pi <project>` launches a pi session with full prompt assembly.

4. **Implement `PiLauncher`** in `core/src/core/launchers/pi.py`:
   - `assemble_prompt()` → writes assembled prompt to `.pi/SYSTEM.md` in project dir
     - Or uses `--system-prompt` flag directly
   - `build_settings()` → writes `.pi/settings.json` with env vars, permissions
   - `exec_session()` → `execvp("pi", [...flags])`

5. **Map Claude CLI flags to pi flags**:

   | Claude CLI | pi CLI |
   |------------|--------|
   | `--system-prompt <text>` | `--system-prompt <text>` |
   | `--settings <file>` | Write `.pi/settings.json` (pi reads natively) |
   | `--setting-sources project,local` | N/A (pi has its own settings merge) |
   | `--add-dir <path>` | Context via AGENTS.md or extension `before_agent_start` |
   | `--plugin-dir <path>` | `-e <path>` or install as pi package |
   | `--resume <id>` | `--session <id>` or `-c` |
   | `--model <name>` | `--model <pattern>` or `--provider <name> --model <id>` |
   | `--session-id <uuid>` | N/A (pi manages session IDs internally) |

6. **Handle .env merging** — two options:
   - **Option A**: Write env vars to `.pi/settings.json` (no extension needed)
   - **Option B**: Extension `before_agent_start` reads `.env` and injects as message
   - **Recommendation**: Option A — simpler, pi natively reads `settings.json`

7. **Handle BASECAMP_* env vars** — write them to `.pi/settings.json` `env` section
   - pi reads settings.json and makes env vars available
   - Alternative: extension `before_agent_start` sets env via `process.env`

8. **Add `basecamp pi` command** to CLI:
   ```
   basecamp pi <project> [--label <label>] [extra pi args]
   ```

### Phase 2: Companion Extension (replace bc-companion plugin)

**Goal**: Replace the Claude Code plugin with a pi extension.

9. **Create `plugins/pi-companion/` extension**:
   ```
   plugins/pi-companion/
   ├── index.ts              # Extension entry point
   ├── session.ts            # Session start/shutdown handlers
   ├── context.ts            # Project context injection
   ├── observer.ts           # Observer ingest on compact/shutdown
   ├── inbox.ts              # Inbox checking
   ├── dispatch-tool.ts      # Worker dispatch tool
   └── package.json
   ```

10. **Map companion hooks to extension events**:

    | Claude Hook | pi Extension Event |
    |-------------|-------------------|
    | `SessionStart` → session-init.sh | `session_start` — session ID from `ctx.sessionManager` |
    | `SessionStart` → project-context.sh | `before_agent_start` — inject context message |
    | `Stop` → check-inbox.sh | `agent_end` — check inbox after each prompt |
    | `PostToolUse` → check-inbox.sh | `tool_execution_end` — immediate inbox check |
    | `PreToolUse` → pretool-ingest.sh | `tool_call` — observer ingest before tool runs |
    | `PreCompact` → hook-process.sh | `session_before_compact` — observer ingest |
    | `SessionEnd` → hook-process.sh | `session_shutdown` — observer ingest + cleanup |
    | `SessionEnd` → session-close.sh | `session_shutdown` — worker close |

11. **BASECAMP_* env var propagation**:
    - In pi, env vars come from `settings.json` or `process.env`
    - Extension reads `process.env.BASECAMP_*` (set by launcher)
    - Worker dispatch: extension spawns `pi` in tmux pane with same env vars

### Phase 3: Skills Migration

**Goal**: Convert Claude Code skills to pi skills format.

12. **Convert dispatch skill** → pi skill in `plugins/pi-companion/skills/dispatch/SKILL.md`:
    - Agent Skills standard format (same concept, different harness)
    - Replace `worker create --name X --dispatch` with pi dispatch tool
    - The skill document stays Markdown; only the CLI commands change

13. **Convert recall skill** → pi skill in `plugins/pi-companion/skills/recall/SKILL.md`:
    - Same `recall` CLI underneath
    - Same SKILL.md format (nearly identical, just update paths/commands)

14. **Convert workers skill** → pi skill in `plugins/pi-companion/skills/workers/SKILL.md`

15. **Convert engineering skills** → pi skills in `plugins/pi-eng/skills/`:
    - `python-development/`, `code-review/`, `data-warehousing/`, etc.
    - Agent Skills standard — same directory + SKILL.md structure
    - Reference docs stay the same
    - Scripts may need minor updates (e.g., `claude` → `pi` if they invoke the CLI)

### Phase 4: Protection Extensions

**Goal**: Replace git-protect and gpg-check plugins with pi extensions.

16. ~~Create `plugins/pi-git-protect/` extension~~ **DONE** — `plugins/pi-git-protect/index.ts`
    - `tool_call` event on `"bash"` with regex matching for force push, ref deletion, clean -f
    - gh command allowlist (read-only + issue ops)
    - mkdir idempotent detection (for future settings.json allowTools use)
    - Packaged as pi package with `package.json`
    - Tested: blocks `git push --force`, `git push --force-with-lease`, `git clean -fdx`; allows normal `git push`

17. ~~GPG check~~ **DEPRECATED** — deleted `plugins/gpg_check/`, removed from marketplace.json, CLAUDE.md, README.md

### Phase 5: Worker Dispatch Redesign

**Goal**: Reimplement worker dispatch using pi's extension/tool API.

18. **Design the dispatch tool** as a pi extension tool:
    ```typescript
    pi.registerTool({
      name: "dispatch_worker",
      description: "Spawn a parallel pi session in a terminal pane",
      parameters: Type.Object({
        name: Type.String(),
        prompt: Type.String(),
        model: Type.Optional(Type.String()),
      }),
      async execute(toolCallId, params, signal, onUpdate, ctx) {
        // 1. Generate worker name with UUID prefix
        // 2. Write prompt to temp file
        // 3. Spawn `pi` in tmux/Kitty pane
        // 4. Track in worker index
      }
    });
    ```

19. **Worker launcher script** changes from `claude` to `pi`:
    - `pi --system-prompt "$(cat prompt.md)" --model sonnet`
    - Or: `pi -e ./pi-companion/index.ts` to load companion extension in worker

20. **Worker index** remains the same file-backed JSON format — the tracking
    mechanism is independent of the agent CLI.

21. **Inbox system** — reimplement using pi's `sendMessage`/`sendUserMessage`:
    - Workers write messages to inbox files
    - Companion extension polls or watches for inbox files
    - Uses `pi.sendMessage()` to inject into main session

### Phase 6: Observer Integration

**Goal**: Update observer to work with pi sessions.

22. **Session transcript location** — pi stores sessions as JSONL in `~/.pi/agent/sessions/`
    - Different format than Claude Code transcripts
    - Parser needs updating to handle pi's JSONL format (entry-based with id/parentId tree)

23. **Agent class update** — observer's `Agent` wraps `claude -p` for LLM calls:
    - Change to `pi -p` (same concept, different CLI)
    - Or: Use pi SDK directly (`createAgentSession` with `SessionManager.inMemory()`)
    - **Recommendation**: Start with `pi -p` for minimal change, consider SDK later

24. **Ingest hooks** — companion extension events replace Claude hooks:
    - `session_before_compact` → ingest transcript before compaction
    - `session_shutdown` → ingest transcript on session end
    - Both have access to session file path via `ctx.sessionManager`

### Phase 7: Engineering Plugin → Pi Package

**Goal**: Convert bc-eng into a proper pi package.

25. **Create `plugins/pi-eng/package.json`** with pi manifest:
    ```json
    {
      "name": "pi-eng",
      "keywords": ["pi-package"],
      "pi": {
        "extensions": ["./extensions"],
        "skills": ["./skills"],
        "prompts": ["./prompts"]
      }
    }
    ```

26. **Convert engineering agents to prompt templates**:
    - `agents/code-reviewer.md` → `prompts/code-reviewer.md`
    - Invoked via `/code-reviewer` in pi

27. **Convert engineering hooks to extension**:
    - `UserPromptSubmit` reminders → `input` event or `before_agent_start`
    - `PreToolUse (Write|Edit)` skill reminder → `tool_call` event for write/edit tools

### Phase 8: CLI Cleanup & Cutover

**Goal**: Make pi the default, deprecate claude backend.

28. **Add `basecamp pi` as primary command**, alias `basecamp claude` to it:
    - `basecamp claude` → prints deprecation warning, delegates to `basecamp pi`
    - Or: `basecamp claude` keeps working with `--launcher pi` as default

29. **Update `basecamp setup`** to:
    - Check for `pi` binary instead of (or in addition to) `claude`
    - Create `~/.pi/agent/settings.json` if needed
    - Install pi-companion extension

30. **Remove Claude-specific code** (after full cutover):
    - `claude_settings.py` (Claude settings mutation)
    - `--setting-sources` handling
    - `.claude-plugin` format support
    - `CLAUDE_COMMAND` constant

---

## Key Architecture Decisions to Make

### 1. Prompt Assembly Strategy

**Option A**: Write assembled prompt to `.pi/SYSTEM.md` before launch
- Pro: Pi natively loads SYSTEM.md, no flags needed
- Con: Pollutes project directory, race conditions with concurrent projects

**Option B**: Use `--system-prompt` flag
- Pro: No file side-effects, clean
- Con: Very long command lines (prompt can be multi-KB)

**Option C**: Use `--system-prompt "$(cat /path/to/prompt.md)"` via launcher script
- Pro: Combines A and B benefits
- Con: Requires launcher script (same pattern as current worker launch.sh)

**Option D**: Extension `before_agent_start` dynamically injects prompt layers
- Pro: Most pi-idiomatic, supports dynamic context
- Con: Extension must be loaded, prompt visible only at runtime

**Recommendation**: **Option C** for launch, **Option D** for runtime context injection.

### 2. Settings Management

**Current**: Mutated Claude settings file with `--settings` flag.
**Pi approach**: Write `.pi/settings.json` with project-local overrides.

- Write `BASECAMP_*` env vars and `.env` merge to `.pi/settings.json` `env` section
- pi natively reads both global and project settings
- No need for `--settings` flag equivalent

### 3. Worker Dispatch Architecture

**Current**: `launch.sh` script that `exec claude ...`
**Pi approach**: `launch.sh` script that `exec pi ...`

- Same tmux/Kitty pane spawning mechanism
- Worker tracking index stays Python-based (basecamp CLI)
- Companion extension in worker provides session hooks

### 4. Plugin Format Transition

**Current**: `.claude-plugin/plugin.json` + `hooks/hooks.json` + shell scripts
**Pi approach**: TypeScript extensions + Markdown skills

- Shell script hooks → TypeScript event handlers
- More powerful, but requires Node.js/TypeScript knowledge
- Skills stay Markdown (portable between harnesses)

### 5. Observer Transcript Parsing

**Current**: Parses Claude Code JSONL format
**Pi approach**: Must parse pi JSONL format (different schema)

- pi sessions use `id`/`parentId` tree structure
- Need a new parser module in observer
- Both formats should be supported during transition

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Prompt assembly differs between claude and pi | A/B test with `--launcher` flag; keep both paths |
| pi extension API gaps (e.g., no PreToolUse equivalent) | `tool_call` event covers this; if missing, file an issue |
| Worker dispatch reliability in pi | Same tmux/Kitty mechanism; test with existing worker patterns |
| Observer transcript format change | Write pi parser alongside Claude parser; dual-format support |
| Skills/agents need updating | Agent Skills standard is portable; mostly Markdown changes |
| User muscle memory (`basecamp claude`) | Alias support; gradual deprecation |
| TypeScript requirement for extensions | Companion extension is the only mandatory one; keep it simple |
| pi not installed on user machines | `basecamp setup` checks and installs if needed |

---

## Implementation Order

**Week 1-2**: Phase 0 (restructure) + Phase 1 (core launch)
- Get `basecamp pi <project>` working with prompt assembly and settings
- Validate basic session works end-to-end

**Week 3-4**: Phase 2 (companion extension) + Phase 3 (skills)
- Replace all companion hooks with extension events
- Convert dispatch/recall/workers skills

**Week 5**: Phase 4 (git-protect) + Phase 5 (worker dispatch)
- Port protection plugins
- Test worker dispatch end-to-end

**Week 6**: Phase 6 (observer) + Phase 7 (engineering package)
- Update observer parser for pi format
- Convert engineering plugin to pi package

**Week 7**: Phase 8 (cleanup + cutover)
- Deprecation warnings
- Documentation updates
- Default to pi backend

---

## Quick-Start: First Working Session

The fastest path to a working `basecamp pi` command:

```bash
# 1. Write assembled prompt to a temp file (same as current)
# 2. Build pi command:
pi --system-prompt "$(cat ~/.basecamp/.cached/myproject/prompt.md)" \
   --model sonnet:medium

# 3. That's it — pi handles the rest natively
```

Everything else (settings, env vars, plugins) can be layered in incrementally.
