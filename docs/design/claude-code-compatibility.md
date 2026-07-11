# Claude Code Compatibility — Design

**Status:** DESIGN · **Scope:** How basecamp behavior projects onto Claude Code · **Decisions locked:** full system-prompt replacement via a launcher; launcher-injection at launch · **Prior art:** a working Claude Code launcher exists in deleted history (see §12) · **Related:** [async-agents](./async-agents.md)

This document describes how basecamp — a full-system-prompt Pi extension — becomes compatible with Claude Code (the CLI). It captures the chosen strategy, the launcher/hooks split it forces, the per-feature mapping, and a phased roadmap. Model-facing guidance projected into Claude Code must read as native Claude Code guidance and must not reference basecamp, Pi, or Pi-only runtime behavior.

---

## 1. Problem statement

basecamp fully replaces Pi's system prompt. [`before_agent_start`](../../pi/system-prompt/prompt.ts) reassembles a layered prompt (mode → working style → environment → capabilities index → project context → runtime env) **every agent turn**, so worktree state, agent mode, and task progress are always current. On top of that, ~15 distinct Pi lifecycle handlers enforce guards, gate risky bash, provision worktrees, and refresh context.

Claude Code is a different runtime. It cannot return a fresh system prompt each turn, its toolset differs from Pi's, and it owns its own UI, worktrees, Plan mode, and subagents. The goal is to reproduce basecamp's *behavior* — full prompt control, project awareness, worktree discipline, bash review — on Claude Code without porting the Pi runtime.

## 2. Goals and non-goals

### Goals

- **Full prompt replacement.** basecamp owns the Claude Code system prompt, as it does in Pi.
- **Project awareness.** Detect the project by git repo root (reusing `basecamp-workspace`) and load project context.
- **Worktree discipline.** Preserve the protected-checkout → execution-worktree model; edits land in the worktree, not the checkout.
- **Bash review.** Gate risky git/gh/shell commands with the existing reviewer ruleset.
- **Environment provisioning.** Run the per-repo `environments` setup command when a worktree is created.
- **Reuse, not rewrite.** Hooks are thin shims over `basecamp` Python subcommands that reuse existing config/workspace/reviewer logic.
- **No global install.** The launcher injects the whole extension bundle at launch (`--plugin-dir`, `--system-prompt-file`, `--settings`); nothing is written into `~/.claude` (see §9).

### Non-goals

- **No Pi runtime port.** No attempt to reproduce Pi's event bus, `plan()` tool, tasks tool, or in-process agent modes wholesale.
- **No swarm coordination port.** The async daemon and wire protocol are Pi-coupled; Claude Code's native subagents replace them. Only the specialist personas project.
- **No custom UI.** Claude Code owns its chrome; basecamp's footer/title map to `statusLine` only.
- **No mid-session prompt reassembly.** The replaced prompt is frozen at launch by design (see §5); volatile state moves to hooks.

## 3. Decision: full prompt replacement

Claude Code exposes several prompt levers. The chosen mechanism is **`claude --system-prompt-file <path>`**, which fully replaces the base prompt for that invocation.

| Lever | Effect | Chosen? |
|-------|--------|---------|
| `--system-prompt-file` | Replaces the entire base prompt (per invocation) | **Yes** — behavioral layers |
| `--append-system-prompt-file` | Appends to Claude Code's base prompt | Candidate for the tools/environment layer only (§6) |
| Output style (`keep-coding-instructions: false`) | Replaces persistently, but static (no per-project dynamic content) | No — cannot carry dynamic project context |
| `CLAUDE.md` | Injected as context, not part of the system prompt | No — not a replacement mechanism |

Because `--system-prompt-file` is a launch-time CLI flag, **full replacement requires a launcher**: a `basecamp` subcommand that assembles the prompt, writes it to a temp file, and execs `claude`. This is the Claude Code analog of Pi's `before_agent_start`.

## 4. Architecture: launcher + hooks

Full replacement splits basecamp's single per-turn hook into **two surfaces with different lifetimes**:

```
basecamp claude  (launcher)                     Claude Code session
  detect project (basecamp-workspace)       ─┐
  select/create worktree                    ─┤ launch-time, computed once
  assemble replaced prompt → tmpfile        ─┤
  write per-session settings → tmpfile      ─┤
  exec: claude \                             │
    --system-prompt-file <prompt.tmp> \      │
    --plugin-dir <pkg>/claude/plugin \       │  ← skills+commands+agents+hooks+mcp
    --settings <settings.tmp> \              │  ← permissions/env/model/statusLine
    --add-dir <additional_dirs> \            │
    [--worktree <label>]                    ─┘
                                              │
                                              ▼
                            plugin hooks.json (loaded via --plugin-dir)
                              SessionStart / UserPromptSubmit  → live orientation
                              PreToolUse(Bash)                 → bash reviewer
                              PreToolUse(Edit|Write)           → path guards
                              PostToolUse                      → context refresh
                              WorktreeCreate                   → env provisioning
                              SessionEnd                       → cleanup
```

- **Launcher owns launch-time composition:** the replaced prompt, cwd, worktree, allowed dirs, model, per-session settings, and the extension bundle — all injected via flags (`--system-prompt-file`, `--plugin-dir`, `--settings`, `--add-dir`). Nothing is installed into `~/.claude` (see §9).
- **Hooks own in-session behavior:** everything basecamp does today outside `before_agent_start` — the `tool_call`/`user_bash` guards, the reviewer, `tool_result` context refresh, `session_shutdown` cleanup, worktree provisioning. They ship in the bundle's `hooks/hooks.json`.

## 5. The frozen-prompt consequence

Pi reassembles the prompt every turn, so it always reflects current worktree/mode/task state. `--system-prompt-file` is **read once at process start and frozen**. Anything basecamp refreshes per turn goes stale.

The resolution is a deliberate division of responsibility:

- **Enforcement lives in hooks, not the prompt.** The `PreToolUse` path guard blocks protected-checkout edits and redirects to the worktree *regardless of what the prompt says*. Correctness does not depend on prompt freshness. This mirrors [`guards.ts`](../../pi/core/project/workspace/guards.ts), which already treats guards as defense independent of the prompt.
- **Live state is injected as context, not prompt.** A `SessionStart`/`UserPromptSubmit` hook emits current worktree, mode, and task state as `additionalContext` each turn. The frozen prompt carries only the durable behavioral layers.
- **Worktree activation is a relaunch, not a mutation.** basecamp's plan→execute handoff becomes: plan in the protected checkout, then relaunch via `claude --worktree <label>` (fresh prompt, native worktree) or `EnterWorktree` + the orient hook. Relaunch is preferred — it rides Claude Code's native worktree machinery and produces a correctly-scoped fresh prompt.

**Consequence:** the replaced prompt describes durable posture (mode, style, project); hooks carry everything volatile. This is a cleaner separation than Pi's monolithic per-turn reassembly, at the cost of two surfaces to maintain.

## 6. Prompt assembly for Claude Code

The launcher reuses basecamp's layered assembly ([`assemblePrompt`](../../pi/system-prompt/prompt.ts)) with two changes.

**Layers carried (full replacement):**

```
mode posture (planning maps to native Plan mode; others as posture text)
working style (engineering / advisor / logseq)
environment + capabilities (see below)
project context (configured context + AGENTS.md/CLAUDE.md)
runtime env block (paths, platform, date, git/worktree state)
```

**The capabilities layer is the real porting cost.** [`buildCapabilitiesIndex`](../../pi/system-prompt/context-builders.ts) and [`environment.md`](../../pi/system-prompt/defaults/environment.md) currently describe *Pi's* toolset — `plan()`, the `bq_query` tool, Pi's worktree model, reviewer routing. Full replacement deletes Claude Code's own tool/safety/output guidance, so this layer must be **rewritten for Claude Code's toolset** (Read/Edit/Bash/Task/Skill/…) and re-verified as that toolset evolves.

Sub-decision on the tools/environment layer only:

- **Full replace** (`--system-prompt-file` carries hand-authored Claude Code tool guidance): maximum control, highest maintenance, drift risk when Claude Code's tools change.
- **Append the tool layer** (`--append-system-prompt-file` keeps Claude Code's own tool/safety guidance; the launcher supplies only basecamp's behavioral layers): loses "pure" replacement but sheds the largest maintenance burden.

**Recommendation:** replace the behavioral layers fully (that is basecamp's value), but let Claude Code keep its own tool/environment guidance. Full replacement of the tools layer buys little and costs the most.

## 7. Hook mapping

Every basecamp Pi lifecycle handler and its Claude Code destination:

| basecamp Pi handler | Behavior | Claude Code mechanism |
|---|---|---|
| `before_agent_start` ([prompt.ts](../../pi/system-prompt/prompt.ts)) | Replace full system prompt | **Launcher** `--system-prompt-file` + **UserPromptSubmit** for volatile deltas |
| `before_agent_start` (tasks) | Inject task/progress reminder | **UserPromptSubmit** `additionalContext` |
| `session_start` (state, mode restore, project detect, workspace init) | Init/restore session | **Launcher** (detect + worktree) + **SessionStart** `additionalContext` |
| `tool_call` guard ([guards.ts](../../pi/core/project/workspace/guards.ts)) | Block protected-checkout edits; retarget relative paths; `cd` bash into worktree | **PreToolUse**(Edit/Write/Bash) → `deny` + `updatedInput` |
| `tool_call` reviewer ([gate.ts](../../pi/bash-reviewer/review.ts)) | LLM approve/route/deny risky bash | **PreToolUse**(Bash) → `permissionDecision: allow\|ask\|deny` |
| `user_bash` | Redirect user `!cmd` to worktree cwd | *Minor gap* — no clean equivalent; launcher cwd covers most cases |
| `tool_result` (context-injection, footer) | Re-inject context after tools | **PostToolUse** `additionalContext` |
| `session_before_compact` / `session_compact` | Preserve + re-inject state across compaction | **PreCompact** / **PostCompact** |
| `session_shutdown` (browser, daemon, companion) | Cleanup | **SessionEnd** / **Stop** |
| `turn_end` (title), footer | Terminal title / footer (project·worktree·mode) | **statusLine** |
| worktree creation + `environments` setup | Provision new worktree (deps, artifacts) | **WorktreeCreate** hook + `.worktreeinclude` |

Both guard behaviors map: Claude Code's `PreToolUse` hook can `deny` **and** rewrite the tool call via `updatedInput`, matching the block-or-retarget logic in `guards.ts` (the `cd <worktree> && <cmd>` rewrite and the protected-path blocks).

> Verify exact hook event names (`WorktreeCreate`, `PostCompact`, etc.) and payload fields against the installed Claude Code version before building on the more recent ones. Load-bearing hooks (`SessionStart`, `UserPromptSubmit`, `PreToolUse`, `SessionEnd`) are stable.

## 8. Implementation pattern: thin hooks over a `basecamp` backend

Each hook is a one-line shell command that shells into the existing Python, reusing `basecamp-workspace`, the reviewer ruleset, and the environment config:

```
SessionStart           → basecamp claude session-start   # project-context additionalContext
UserPromptSubmit       → basecamp claude orient          # current worktree/mode/task state
PreToolUse(Bash)       → basecamp claude bash-review      # reviewer ruleset → allow/ask/deny
PreToolUse(Edit|Write) → basecamp claude path-guard       # protected-checkout / worktree enforcement
WorktreeCreate         → basecamp claude provision        # run per-repo environments setup command
SessionEnd             → basecamp claude session-end        # cleanup
```

**Reviewer context.** The reviewer needs recent human messages ([`buildGateContext`](../../pi/bash-reviewer/review.ts) takes `recent_human_messages`). The `PreToolUse` payload provides `transcript_path`; `basecamp claude bash-review` reads that JSONL to reconstruct recent turns. No new plumbing.

**Launcher.** `basecamp claude` (candidate alias `bcc`) detects the project, assembles the prompt, writes the per-session settings, and execs `claude` with the flags in §4. It is a CLI the user runs, not a hook, so it lives in the Python package.

## 9. Packaging: launcher-injection at launch

basecamp does **not** pre-install anything into `~/.claude`. The launcher owns the invocation and injects everything at launch, so there is no global config to mutate defensively (no managed markers, conflict guards, or merge logic). This is also the faithful analog of how basecamp already works in Pi — a **session-scoped extension loaded at launch**, not a global install.

Confirmed launch-flag surface (all ephemeral, per-invocation, merged with any existing hierarchy): `--system-prompt-file`, `--plugin-dir` (loads a local plugin's skills + commands + agents + `hooks/hooks.json` + `.mcp.json` in a normal session, no marketplace), `--settings` (JSON or file: permissions/env/model/statusLine), `--agents` (inline JSON), `--mcp-config`, `--add-dir`. There is **no `--skills-dir`** — skills come only from disk or a plugin, so the bundle is a plugin loaded via `--plugin-dir`.

The extension bundle lives **inside the installed Python package** and is referenced by path — never copied:

```
<pkg>/claude/
├── projection.toml                  # manifest: which prompt layers, agents, skills, commands to assemble
├── plugin/                          # loaded via `claude --plugin-dir <this>`
│   ├── .claude-plugin/plugin.json
│   ├── hooks/hooks.json             # the §8 hook wiring
│   ├── agents/*.md                  # specialist personas (native subagents)
│   ├── skills/                      # bundled from <context>/skills
│   ├── commands/*.md                # prompt-driven commands (/create-pr, …)
│   └── bin/                         # shim resolving `basecamp` for hooks
└── system-prompts/                  # Claude Code rewrite of modes/styles/environment/capabilities
```

- **No install step.** The launcher passes `--plugin-dir <pkg>/claude/plugin`; the prompt and per-session `--settings` are written to ephemeral temp files each run. Uninstalling basecamp removes everything; the bundle is versioned with the package.
- **`src/basecamp/claude/`** (launcher module) owns launch and prompt assembly. It reuses the prompt-assembly content and the reviewer/workspace Python; there is no global install step.
- **Hooks live in the bundle** (`hooks/hooks.json`), loaded by `--plugin-dir` — versioned and portable, never scattered in user `settings.json`.

**Plain-`claude` tradeoff.** Because nothing is installed globally, a bare `claude` (not `basecamp claude`) is vanilla Claude Code. In Pi this never arises — once registered, every `pi` is basecamp. To get "always on," alias `claude="basecamp claude"` rather than reaching for a global install; a global install refragments ownership and reintroduces exactly the conflict-guard problems a launcher avoids.

**Optional distribution (later, orthogonal).** A standalone marketplace plugin — installable with `/plugin` and usable in plain `claude` without the launcher — is a distribution choice for non-launcher users, not a requirement for the launcher, and is out of scope for the core path.

## 10. Feature fidelity map

| basecamp capability | Claude Code destination | Fidelity |
|---|---|---|
| Full layered prompt | `--system-prompt-file` (launcher) | High (frozen; §5) |
| Working styles | Prompt layer (or output styles) | High |
| Project detection + context | Launcher + SessionStart hook | High |
| Bash reviewer | PreToolUse(Bash) hook | High |
| Worktree guards | PreToolUse(Edit/Write/Bash) hook | High |
| Worktree lifecycle | Native worktrees + relaunch | Medium (convention clash, §11) |
| Env provisioning | WorktreeCreate hook + `.worktreeinclude` | High |
| Specialist agents | Native subagents (bundled `agents/*.md`) | High (personas only) |
| Skills | Bundled plugin, loaded via `--plugin-dir` | High |
| Prompt-driven commands | Bundled `commands/*.md` | High |
| Planning mode | Native Plan mode | Medium |
| Other agent modes (analysis/supervisor/copilot) | Posture text only | Low |
| Model aliases (`fast`→haiku) | settings `model` + per-agent `model:` | Medium |
| Async swarm | Native subagents (Task, `isolation: worktree`) | Coordination replaced, personas port |
| Companion / browser / tasks tools | Claude Code native / MCP | Drop or MCP |

## 11. Open decisions

- **Tools/environment layer:** full-replace vs. `--append` (§6). Recommendation: append that layer.
- **Worktree conventions:** basecamp uses `~/.worktrees/<org>/<name>/<label>/` with `wt/<label>` branches and migration logic; Claude Code native uses `.claude/worktrees/<name>/` off `origin/HEAD`. Adopt Claude Code's convention, or attach basecamp-created worktrees via `git worktree` + `EnterWorktree`. Needs a call.
- **Agent modes:** keep planning (→ Plan mode); decide whether analysis/supervisor/copilot survive as posture text or are dropped.
- **`user_bash` gap:** whether the minor loss of user-`!cmd` cwd redirection matters given the launcher sets cwd.

## 12. Prior art (recover, don't rebuild)

basecamp **was** a Claude Code launcher-plus-plugins app before it migrated to Pi at commit `6674cc4` ("feat: migrate to pi extension architecture"). The full pre-migration implementation is recoverable at `6674cc4^` and validates this entire design — full-prompt replacement, `--plugin-dir` bundles, and `--settings` env injection were all shipped in production. Recover and adapt it rather than building greenfield.

Reusable pieces at `6674cc4^`:

- `core/src/core/cli/launch.py` — `execute_launch()`: project/path resolution, worktree get-or-create by label, prompt assembly, builds `claude` with `--system-prompt` + `--plugin-dir` + `--add-dir` + `--settings <file> --setting-sources project,local`, chdir, exec via a tmux/direct terminal backend. Also path-based launch and shell completions.
- `core/src/core/config/claude_settings.py` — `build_session_settings()`: strips `apiKeyHelper`, merges project `.env` into `settings.env`, pre-authorizes scratch dirs, injects `BASECAMP_*`. Directly portable (`atomic_write_json` still exists in `basecamp.core.files`).
- `.claude-plugin/marketplace.json` + `plugins/*/.claude-plugin/plugin.json` — the bundled plugins (bc-collab, bc-cursor, bc-eng, bc-git-protect, bc-gpg-check, bc-private, companion). `bc-git-protect` is the prior bash-reviewer analog.

**The gap vs. then:** the current Python packages (`basecamp.core`, `basecamp.workspace`) expose project config but **not** git-root detection, prompt assembly, or worktree helpers — those moved to TypeScript (now split across `pi/system-prompt/` and `pi/core/`). So the recovered launcher must re-establish Python-side project detection and a Claude-Code-specific prompt assembly (§6). Everything else ports almost verbatim.

## 13. Phased roadmap

1. **Bundle + launcher walking skeleton.** `<pkg>/claude/plugin/` (specialist agents, skills, commands) + rewritten `system-prompts/` + a minimal `basecamp claude` that detects the project, assembles the prompt, and execs `claude --system-prompt-file … --plugin-dir … --add-dir …`. Proves launcher-injection end to end — no install step.
2. **Full prompt assembly.** Port the layered assembly to the launcher; rewrite the environment/capabilities layer for Claude Code's toolset (§6).
3. **Enforcement hooks.** `PreToolUse` bash reviewer + path guards over `basecamp claude bash-review` / `path-guard`, shipped in the bundle's `hooks/hooks.json`. This is where worktree discipline and safety appear.
4. **Orientation + provisioning hooks.** `SessionStart`/`UserPromptSubmit` context, `WorktreeCreate` env provisioning, `SessionEnd` cleanup.
5. **Reconcile worktree conventions** (§11) and finalize the plan→execute relaunch flow.
