# system-prompt

The context/prompt layer — assembles the replacement system prompt on every agent start.

Basecamp fully *replaces* pi's default system prompt rather than appending to it, so this domain must provide everything: environment, working style, project context, and the tool/skill/agent index. It binds `before_agent_start`, builds the layered prompt, and returns it.

## What it does

- **`prompt.ts`** — the `before_agent_start` hook + `assemblePrompt`. Layer order: read-only posture → mode posture → working style (or an `--agent-prompt` override) → environment → capabilities index (tools · skills · agents) → project context → repo-Logseq (copilot only) → environment block. Also the file loader with its user-override fallback.
- **`context-builders.ts`** — pure fragment builders: worktree warning, unsafe-edit guidance, project-context block, capabilities index.
- **`defaults/`** — the shipped fragments: `environment.md`, `modes/<mode>.md`, `styles/<style>.md`. Each is overridable per-user (see below).

## Defaults ↔ user override

`loadPromptFile` / `loadWorkingStyle` read the user dir first (`~/.pi/basecamp/prompts` · `.../styles`), then fall back to `defaults/`.

## Registration

Registered in `extension.ts` immediately after `workspace`. Because it binds at `before_agent_start` — which fires after every `session_start` — registration order is not load-bearing: it reads whatever workspace and project state resolved during session start.

## Dependencies

- **core** (`#core/*`): `agent-mode` (+ the `isCopilotMode` predicate), `catalog`, `#core/project` (project state · context-file loader · repo-logseq), `#core/workspace` (workspace state), host paths.
