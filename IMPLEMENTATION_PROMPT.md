# Implementation Prompt: Convert bc-eng to pi Extension + Skills Package

## Task

Convert the `bc-eng` Claude Code plugin into a pi-coding-agent package containing:
1. A TypeScript extension (replaces `hooks.json` + shell scripts)
2. Pi skills (replaces Claude Code skills AND agents — all collapsed into skills)

Write everything into a new directory: `plugins/pi-eng/`

## Source Material

The current bc-eng plugin lives at `plugins/engineering/`. Here is its complete structure:

```
plugins/engineering/
├── .claude-plugin/plugin.json           # IGNORE (Claude-specific format)
├── hooks/hooks.json                     # REPLACE with TypeScript extension
├── scripts/
│   ├── session-setup.sh                 # → extension session_start event
│   ├── skill-reminder.sh                # → extension tool_call event
│   ├── allow-pr-comments.sh             # → cannot port (auto-allow gap)
│   └── allow-pr-push.sh                 # → cannot port (auto-allow gap)
├── agents/                              # → skills/ (each becomes SKILL.md in a directory)
│   ├── context-gatherer.md
│   ├── code-reviewer.md
│   ├── security-reviewer.md
│   ├── test-reviewer.md
│   ├── code-simplifier.md
│   ├── comment-analyzer.md
│   ├── python-backend.md
│   └── python-testing.md
└── skills/                              # → skills/ (nearly verbatim)
    ├── code-review/
    │   ├── SKILL.md
    │   └── references/DIMENSIONS.md
    ├── code-documentation/
    │   └── SKILL.md
    ├── data-warehousing/
    │   ├── SKILL.md
    │   └── references/ (5 .md files)
    ├── marimo/
    │   └── SKILL.md
    ├── pr-comments/
    │   └── SKILL.md
    ├── pr-walkthrough/
    │   └── SKILL.md
    ├── pull-request/
    │   └── SKILL.md
    ├── python-development/
    │   ├── SKILL.md
    │   └── references/ (8 .md files)
    └── sql/
        ├── SKILL.md
        └── references/ (5 .md files)
```

## Target Structure

```
plugins/pi-eng/
├── package.json                  # Pi package manifest
├── extension/
│   └── index.ts                  # Single extension file
└── skills/                       # All 17 skills (9 original + 8 from agents)
    ├── code-review/
    ├── code-documentation/
    ├── data-warehousing/
    ├── marimo/
    ├── pr-comments/
    ├── pr-walkthrough/
    ├── pull-request/
    ├── python-development/
    ├── sql/
    ├── code-reviewer/            ← was agents/code-reviewer.md
    ├── code-simplifier/          ← was agents/code-simplifier.md
    ├── comment-analyzer/         ← was agents/comment-analyzer.md
    ├── context-gatherer/        ← was agents/context-gatherer.md
    ├── python-backend/          ← was agents/python-backend.md
    ├── python-testing/          ← was agents/python-testing.md
    ├── security-reviewer/       ← was agents/security-reviewer.md
    └── test-reviewer/           ← was agents/test-reviewer.md
```

## Part 1: Extension (`extension/index.ts`)

The extension replaces all 4 shell scripts and the hooks.json. It is a single `export default function(pi: ExtensionAPI)` module.

### What each script does and how to port it:

#### 1. `session-setup.sh` → `session_start` event

**Current behavior**: On SessionStart, detect git repo name, export `GIT_REPO` to `CLAUDE_ENV_FILE`, create `/tmp/claude-workspace/$GIT_REPO/pull_requests/` and `pr-comments/` dirs.

**pi port**: On `session_start`, detect git repo name via `pi.exec("git", ...)`, create the same directories. Since pi doesn't have `CLAUDE_ENV_FILE`, store `GIT_REPO` in a module-level variable that other event handlers can reference. Also write it to `process.env` so bash commands the LLM runs can see it.

```typescript
let gitRepo: string | undefined;

pi.on("session_start", async (_event, ctx) => {
  try {
    const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd: ctx.cwd });
    gitRepo = path.basename(result.stdout.trim());
  } catch {
    gitRepo = path.basename(ctx.cwd);
  }
  process.env.GIT_REPO = gitRepo;

  const scratch = process.env.BASECAMP_SCRATCH_DIR || `/tmp/claude-workspace/${gitRepo}`;
  await fs.mkdir(path.join(scratch, "pull_requests"), { recursive: true });
  await fs.mkdir(path.join(scratch, "pr-comments"), { recursive: true });
});
```

#### 2. `skill-reminder.sh` → `tool_call` event

**Current behavior**: On PreToolUse (Write|Edit), check if `file_path` ends in `.py` or `.sql`. If so, inject `additionalContext` telling the model to load the relevant skill.

**pi port**: On `tool_call` for `"write"` or `"edit"` tools, check `event.input.path` for file extension. If `.py`, inject a steering message suggesting the python-development skill. If `.sql`, suggest the sql skill.

**IMPORTANT**: In Claude, the PreToolUse hook could return `additionalContext` which got silently injected into the model's context. In pi, there's no direct equivalent. Instead, use `pi.sendMessage()` with `deliverAs: "steer"` to inject a steering message that reminds the model about relevant skills. This is slightly different (it's a visible message, not invisible context) but achieves the same goal.

```typescript
pi.on("tool_call", async (event, _ctx) => {
  if (event.toolName === "write" || event.toolName === "edit") {
    const filePath: string = event.input.path || "";
    if (filePath.endsWith(".py")) {
      pi.sendMessage("Python file detected — consider loading /skill:python-development for best practices.", {
        deliverAs: "steer",
      });
    } else if (filePath.endsWith(".sql")) {
      pi.sendMessage("SQL file detected — consider loading /skill:sql for best practices.", {
        deliverAs: "steer",
      });
    }
  }
});
```

**Alternative approach**: Instead of injecting a message on every write/edit (which could be noisy), skip this entirely since pi skills are auto-discovered and the model can see them in the system prompt. Consider making this behavior configurable.

#### 3. `allow-pr-comments.sh` and `allow-pr-push.sh` — CANNOT PORT

**Current behavior**: On PreToolUse (Bash), if the command matches certain `gh` patterns, return `permissionDecision: "allow"` to bypass Claude's permission dialog.

**pi port**: **This pattern CANNOT be directly ported.** Pi's `tool_call` event can only block (`{ block: true }`), not explicitly allow. There is no `permissionDecision: "allow"` equivalent. Users should configure their own bash permission preferences in settings.json. Add a comment in the extension documenting this gap.

#### 4. `UserPromptSubmit` echo reminders → `before_agent_start` event (optional)

**Current behavior**: On UserPromptSubmit, echo two reminder strings about checking skills and agents.

**Recommendation**: Omit this. Pi's startup header already shows loaded skills, and the system prompt includes skill descriptions. The Claude plugin needed these reminders because Claude Code didn't surface skill availability as prominently. In pi, this is redundant.

### Full extension template:

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs/promises";
import * as path from "node:path";

let gitRepo: string | undefined;

export default function (pi: ExtensionAPI) {
  // === session_start: set up git repo name and scratch directories ===
  pi.on("session_start", async (_event, ctx) => {
    try {
      const result = await pi.exec("git", ["rev-parse", "--show-toplevel"], { cwd: ctx.cwd });
      gitRepo = path.basename(result.stdout.trim());
    } catch {
      gitRepo = path.basename(ctx.cwd);
    }
    process.env.GIT_REPO = gitRepo;

    const scratch = process.env.BASECAMP_SCRATCH_DIR || `/tmp/claude-workspace/${gitRepo}`;
    await fs.mkdir(path.join(scratch, "pull_requests"), { recursive: true });
    await fs.mkdir(path.join(scratch, "pr-comments"), { recursive: true });

    ctx.ui.notify(`bc-eng: repo=${gitRepo}, scratch=${scratch}`, "info");
  });

  // === tool_call: skill reminders on write/edit ===
  pi.on("tool_call", async (event, _ctx) => {
    if (event.toolName === "write" || event.toolName === "edit") {
      const filePath: string = event.input.path || "";
      if (filePath.endsWith(".py")) {
        pi.sendMessage(
          "Python file detected — consider loading /skill:python-development for best practices.",
          { deliverAs: "steer" }
        );
      } else if (filePath.endsWith(".sql")) {
        pi.sendMessage(
          "SQL file detected — consider loading /skill:sql for best practices.",
          { deliverAs: "steer" }
        );
      }
    }
  });

  // NOTE: allow-pr-comments.sh and allow-pr-push.sh cannot be directly ported.
  // Pi's tool_call event can only block, not auto-allow. There is no
  // permissionDecision: "allow" equivalent. Users should configure their own
  // bash permission preferences in settings.json or approve gh commands
  // when prompted.
}
```

## Part 2: Skills (`skills/`) — Original 9 Skills

Port the 9 skills from `plugins/engineering/skills/` to `plugins/pi-eng/skills/`.

**This is nearly a 1:1 copy.** The SKILL.md format is the Agent Skills standard, which pi implements directly. The only changes needed:

1. **Remove Claude-specific frontmatter fields**: `allowed-tools`, `hooks`, `argument-hint` are not in the Agent Skills spec. Pi will warn about them but still load the skill.
   - `allowed-tools: Bash(git:*), Bash(gh:*)` → Remove. Pi doesn't enforce tool allowlists from skill frontmatter.
   - `hooks: PreToolUse ...` → Remove. This was handled by shell scripts, now handled by the extension.
   - `argument-hint` → Remove. Not in the spec.

2. **`disable-model-invocation: true`** → Keep this. Pi supports this per the Agent Skills spec: "When `true`, skill is hidden from system prompt. Users must use `/skill:name`."

3. **Update command references**: Some skills reference Claude-specific tool names. Check for:
   - `AskUserQuestion` tool → Not available in pi. Replace with: "ask the user a clarifying question" (the model will just ask in text).
   - `TodoWrite` tool → Not available in pi by default. Replace with: "track tasks in a TODO.md file" or just remove references.
   - Tool names like `Read`, `Write`, `Edit`, `Bash`, `Grep`, `Glob` → pi uses lowercase: `read`, `write`, `edit`, `bash`, `grep`, `find`, `ls`. Update references.

4. **Update path references**: Skills reference `/tmp/claude-workspace/{repo}/` paths. These work fine if `BASECAMP_SCRATCH_DIR` is set, or the extension creates them. Keep as-is.

5. **Copy all reference files verbatim**: The `references/` subdirectories contain detailed documentation. These are just Markdown files linked from SKILL.md — they work identically in pi.

### Specific skill frontmatter changes:

**code-review/SKILL.md**:
- Remove `allowed-tools: Bash(git:*), Bash(gh:*)` from frontmatter
- Keep everything else

**pr-comments/SKILL.md**:
- Remove `allowed-tools` and `hooks` from frontmatter
- Keep `disable-model-invocation: true`

**pull-request/SKILL.md**:
- Remove `allowed-tools` and `hooks` from frontmatter
- Keep `disable-model-invocation: true`
- Replace `AskUserQuestion` references with "ask the user"
- Update `$BASECAMP_REPO` references — this env var will be set by the extension if running under basecamp, otherwise use `$GIT_REPO`

**pr-walkthrough/SKILL.md**:
- Remove `allowed-tools` from frontmatter

**python-development, sql, data-warehousing, marimo, code-documentation**:
- No frontmatter changes needed — pure content skills with no Claude-specific fields

## Part 3: Skills (`skills/`) — 8 Agent-to-Skill Conversions

Convert each agent from `plugins/engineering/agents/*.md` into a skill directory `plugins/pi-eng/skills/<name>/SKILL.md`.

### Why skills, not prompt templates?

The agents are detailed instructional documents (context-gatherer, code-reviewer, etc.). Skills give them progressive disclosure — the description appears in the system prompt, and the full SKILL.md content loads on-demand via `/skill:name`. This is better for long prompts than prompt templates, which dump everything into the message at once. It also avoids a separate `prompts/` directory concept when skills do the same job.

### Conversion steps for each agent:

1. Create directory `skills/<name>/` (e.g., `skills/code-reviewer/`)
2. Create `SKILL.md` inside it
3. **Frontmatter**: Keep only `name` and `description`. Strip `model`, `color`, and any other Claude-specific fields.
4. **Body**: Copy the agent's Markdown content verbatim

**Valid skill frontmatter fields** (per Agent Skills spec):
| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Must match parent directory. Lowercase a-z, 0-9, hyphens. |
| `description` | Yes | Max 1024 chars. What the skill does and when to use it. |
| `license` | No | License name or reference. |
| `compatibility` | No | Max 500 chars. Environment requirements. |
| `metadata` | No | Arbitrary key-value mapping. |
| `allowed-tools` | No | Space-delimited list of pre-approved tools (experimental). |
| `disable-model-invocation` | No | When `true`, hidden from system prompt. |

**Fields to REMOVE from agent frontmatter**:
- `model: opus` — Pi doesn't support model selection from skill frontmatter. Users pick the model themselves (Ctrl+L).
- `color: green` — Purely a Claude Code UI concept. Not in the spec.

**Example conversion** — `agents/code-reviewer.md`:

Before (Claude agent):
```markdown
---
name: code-reviewer
description: Use this agent to review code for adherence to project standards, best practices, and bug detection. Invoke after writing or modifying code, especially before committing changes or creating pull requests. Works standalone or as part of a multi-reviewer workflow. The agent needs to know which files to review—by default, it reviews unstaged changes from git diff.
model: opus
color: green
---

You are an expert code reviewer specializing in software architecture, design patterns, and code quality. Your role is to review code against project CLAUDE.md, the **code-review** skill methodology, and your available skills with high precision to minimize false positives.
...
```

After (pi skill at `skills/code-reviewer/SKILL.md`):
```markdown
---
name: code-reviewer
description: Review code for adherence to project standards, best practices, and bug detection. Invoke after writing or modifying code, especially before committing changes or creating pull requests. Works standalone or as part of a multi-reviewer workflow. The agent needs to know which files to review—by default, it reviews unstaged changes from git diff.
---

You are an expert code reviewer specializing in software architecture, design patterns, and code quality. Your role is to review code against project CLAUDE.md, the **code-review** skill methodology, and your available skills with high precision to minimize false positives.
...
```

### All 8 conversions:

| Source Agent | Target Directory | Frontmatter Changes |
|---|---|---|
| `agents/context-gatherer.md` | `skills/context-gatherer/SKILL.md` | Remove `model: opus`, `color: pink` |
| `agents/code-reviewer.md` | `skills/code-reviewer/SKILL.md` | Remove `model: opus`, `color: green` |
| `agents/security-reviewer.md` | `skills/security-reviewer/SKILL.md` | Remove `model: opus`, `color: red` |
| `agents/test-reviewer.md` | `skills/test-reviewer/SKILL.md` | Remove `model: opus`, `color: yellow` |
| `agents/code-simplifier.md` | `skills/code-simplifier/SKILL.md` | Remove `model: opus`, `color: blue` |
| `agents/comment-analyzer.md` | `skills/comment-analyzer/SKILL.md` | Remove `model: opus`, `color: green` |
| `agents/python-backend.md` | `skills/python-backend/SKILL.md` | Remove `color: blue` (no `model` field) |
| `agents/python-testing.md` | `skills/python-testing/SKILL.md` | Remove `color: green` (no `model` field) |

**Note on `model: opus`**: The original agents specified `model: opus` to ensure high-quality reasoning. Pi doesn't support model selection from skill frontmatter. If you want to preserve this hint, add a comment at the top of the skill body: `<!-- For best results, switch to opus before invoking (Ctrl+L → opus) -->`. Or just trust the user to pick the right model.

**Note on `CLAUDE.md` references**: Some agent bodies reference "project CLAUDE.md". These references still work in pi — pi also reads `CLAUDE.md` files. No changes needed.

## Part 4: Package Manifest (`package.json`)

```json
{
  "name": "pi-eng",
  "version": "1.0.0",
  "description": "Engineering resources for pi: extension and skills for code review, Python development, SQL, PRs, and more.",
  "keywords": ["pi-package"],
  "pi": {
    "extensions": ["./extension"],
    "skills": ["./skills"]
  }
}
```

## Implementation Checklist

- [ ] Create `plugins/pi-eng/` directory structure
- [ ] Write `package.json` with pi manifest
- [ ] Write `extension/index.ts` — the TypeScript extension
  - [ ] `session_start` handler (git repo detection, scratch dirs)
  - [ ] `tool_call` handler (skill reminders on write/edit)
  - [ ] Comments documenting what couldn't be ported (auto-allow patterns)
- [ ] Copy 9 original skills from `plugins/engineering/skills/` to `plugins/pi-eng/skills/`
  - [ ] Update frontmatter in code-review/SKILL.md
  - [ ] Update frontmatter in pr-comments/SKILL.md
  - [ ] Update frontmatter in pull-request/SKILL.md
  - [ ] Update frontmatter in pr-walkthrough/SKILL.md
  - [ ] Copy all other skills verbatim (python-development, sql, data-warehousing, marimo, code-documentation)
  - [ ] Copy all `references/` subdirectories verbatim
- [ ] Convert 8 agents to skill directories in `plugins/pi-eng/skills/`
  - [ ] context-gatherer/SKILL.md (remove `model: opus`, `color: pink`)
  - [ ] code-reviewer/SKILL.md (remove `model: opus`, `color: green`)
  - [ ] security-reviewer/SKILL.md (remove `model: opus`, `color: red`)
  - [ ] test-reviewer/SKILL.md (remove `model: opus`, `color: yellow`)
  - [ ] code-simplifier/SKILL.md (remove `model: opus`, `color: blue`)
  - [ ] comment-analyzer/SKILL.md (remove `model: opus`, `color: green`)
  - [ ] python-backend/SKILL.md (remove `color: blue`)
  - [ ] python-testing/SKILL.md (remove `color: green`)
- [ ] Test: `pi -e ./plugins/pi-eng/extension/index.ts` loads without errors
- [ ] Test: `/skill:python-development` loads in interactive mode
- [ ] Test: `/skill:code-reviewer` loads in interactive mode
- [ ] Verify no frontmatter warnings in pi output

## Pi Extension API Reference (Quick)

```typescript
import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { isToolCallEventType } from "@mariozechner/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  // Events
  pi.on("session_start", async (event, ctx) => { ... });
  pi.on("session_shutdown", async (event, ctx) => { ... });
  pi.on("before_agent_start", async (event, ctx) => {
    // event.prompt, event.systemPrompt
    // return { message: {...}, systemPrompt: "..." }
  });
  pi.on("tool_call", async (event, ctx) => {
    // event.toolName, event.input (mutable)
    // return { block: true, reason: "..." } to block
  });
  pi.on("tool_result", async (event, ctx) => { ... });
  pi.on("input", async (event, ctx) => { ... });
  pi.on("agent_start", async (event, ctx) => { ... });
  pi.on("agent_end", async (event, ctx) => { ... });

  // Tools
  pi.registerTool({ name, label, description, parameters, execute });

  // Commands
  pi.registerCommand("name", { description, handler: async (args, ctx) => {} });

  // Messages
  pi.sendMessage(content, { deliverAs: "steer" | "followUp" | "nextTurn" });
  pi.sendUserMessage(text, { deliverAs: "steer" | "followUp" });

  // Execution
  const result = await pi.exec("git", ["status"], { cwd, timeout: 5000 });

  // UI
  ctx.ui.notify("message", "info" | "warning" | "error");
  ctx.ui.confirm("Title", "Message?");  // → boolean
  ctx.ui.select("Title", ["opt1", "opt2"]);  // → string | undefined
}

// Context
ctx.cwd          // working directory
ctx.sessionManager  // session state
ctx.signal       // abort signal (during tool events)
ctx.hasUI        // false in print/json mode
```

## Key Constraints

1. **No build step required** — pi uses jiti to load TypeScript directly. Write `.ts`, not compiled `.js`.
2. **Single extension file** — `extension/index.ts` is the entry point. Keep it under ~150 lines. If it grows, split into modules in `extension/` and import them.
3. **Skills must have valid SKILL.md** — `name` and `description` in frontmatter are required. `name` must match parent directory name. Lowercase a-z, 0-9, hyphens only.
4. **Don't try to replicate auto-allow** — Pi doesn't support it. Document the gap and move on.
5. **Use `isToolCallEventType` for typed access** — e.g., `isToolCallEventType("bash", event)` gives typed `event.input.command`.
6. **`event.input` is mutable** — you can patch tool args in place, but be careful.
7. **Test with `pi -e ./path/to/extension/index.ts`** — this loads the extension for the current session only.
8. **The `@sinclair/typebox` and `@mariozechner/pi-ai` packages are available** — for schema definitions and StringEnum.
9. **Node.js builtins work** — `node:fs`, `node:path`, `node:child_process`, etc.
