# System Prompt

The context/prompt layer: assembles the replacement system prompt on every agent start.

Basecamp fully *replaces* pi's default system prompt rather than appending to it, so this domain must provide everything: environment, working style, project context, and the skill/agent index. Tools are the one capability the prompt never lists; their contracts (description + parameter schema) reach the model through the API tools array on every request, so a prompt listing would be a second copy of the same text in the same cached prefix. It binds `before_agent_start`, builds the prompt, and returns it.

## Architecture: 6 categories, 9 blocks

The prompt is assembled from blocks grouped into categories, in this order:

| # | Category | Block | Source | Included when |
|---|----------|-------|--------|---------------|
| 1 | Constraints | read-only | `defaults/modes/read-only.md` | `--read-only` |
| 2 | Posture | mode | `defaults/modes/{analysis,planning,work,copilot}.md` | primary session |
| 3 | | persona | `#core/swarm` `builtin/*.md` (via `agentPrompt`) | dispatched agent |
| 4 | Style | role style | `defaults/styles/{engineering,advisor,logseq}.md` | user-facing, non-copilot |
| 5 | | voice | `defaults/voice.md` | primary session (depth 0) |
| 6 | | craft | `defaults/craft.md` | **always** |
| 7 | Capabilities | index | `buildCapabilitiesIndex` | always |
| 8 | Project | repo context · repo memory | `buildProjectContext` · `buildRepoLogseqContext` | always · copilot |
| 9 | Environment | session facts · runtime | `defaults/environment.md` · `buildEnvBlock` | always |

Two structural rules keep it from re-accreting.

### Ownership rule: one question per layer

Each layer answers exactly one question. When guidance appears in the wrong layer it gets duplicated, because the layer that should own it still needs it.

| Layer | Answers |
|-------|---------|
| `environment.md` | What is true here? (machine, sandbox, guards, tooling) |
| `buildEnvBlock` | What is true right now? (cwd, repo, worktree, date) |
| tool description | How do I call this? |
| `modes/*` | **What are we doing?** |
| `styles/*` | **Who are you and how do you work?** (selectable role) |
| `voice.md` | **How is output shaped?** (any primary session) |
| `craft.md` | **How is code written?** (unconditional) |
| skills | How do I do this well, in depth? |
| project context | What's non-obvious about this repo? |

Mode and style are the *what* and the *how* of a session. Test a fragment by asking which it is: "you implement and integrate" is a what (mode); "you are a partner, not a follower" is a how (style).

Consequences:

- **Tool mechanics never go in a prompt fragment.** The API tools array delivers every registered tool description verbatim, so restating a calling contract in a fragment presents it twice in one request. Put the contract in the tool description; keep only policy a tool cannot assert (for example "always maintain tasks") in the style. This is why `buildCapabilitiesIndex` lists skills and agents but no tools.
- **Cross-tool sequencing goes in a skill**, not a fragment; no single tool description owns a multi-tool workflow. The `workstreams` skill is the worked example.
- **Machine facts stay in `environment.md`, even when a skill covers the topic.** Python/uv lives here; `python-development` owns how to write good Python.
- **Taste never goes in `environment.md`.** Facts are not preferences.

### Consumer-divergence test: when a block is justified

A block boundary is only worth having if two consumers actually disagree about it. If every consumer takes two blocks together, they are one block. The real consumer list is: primary × mode, ad-hoc deliverable runs, report personas, and read-only variants. The test is what keeps the block count at 9 rather than ~69: an earlier semantic decomposition (every topic shift becoming a block) was rejected because it converts authored prose into config, which is harder to read and makes the assembled prompt harder to reason about.

The three Style blocks pass it, because each adjacent pair genuinely diverges:

| Block | Consumers | Diverges from the next because |
|---|---|---|
| role style | user-facing, non-copilot | copilot takes voice but loads no role style |
| voice | any primary session, copilot included | a dispatched agent's reader is not a user reading a conversation |
| craft | every consumer, personas included | a persona still writes code |

Voice is excluded for dispatched agents because its rules presuppose a human reader in a conversation; a report persona's reader is the primary agent parsing one artifact, and the persona's own template already mandates that artifact's shape. Voice would load *after* the persona block, so on recency it would win and reshape the persona's output against its template.

### Generator vs. authored

The category boundary encodes this split. Constraints, Posture, and Style are **authored prose** in `defaults/` (user-overridable). Capabilities, Project, and the runtime half of Environment are **generated** from runtime state. Do not interpolate authored prose into a generator, and do not hand-maintain in prose what a generator can derive.

Prompt-block ordering is chosen for coherence rather than positional emphasis: this model generation does not weight end-of-context instructions more heavily.

## What it does

- **`prompt.ts`**: the `before_agent_start` hook + `assemblePrompt`, plus the file loaders and their user-override fallback.
- **`context-builders.ts`**: pure fragment builders: worktree warning, unsafe-edit guidance, project-context block, capabilities index.
- **`defaults/`**: the shipped fragments: the non-selectable top-level files (`environment.md`, `voice.md`, `craft.md`) and the selectable sets `modes/<mode>.md`, `styles/<style>.md`.

### Copilot is a mode that carries its own manner

Copilot is a distinct *activity*: orient the repo, make the choice set clear, shape and stage workstreams, curate repo memory, so it is a mode, not a style. It is also the one mode that loads **no** style file, because no selectable style fits: `engineering` asserts "you implement directly" and copilot does not implement; `advisor` drags prose-over-bullets and a research section; `logseq` assumes cwd is the graph root. The one style block it does load is voice, which reaches every primary session regardless of mode.

What remains inline is a short "Work with the user" section that names which artifact to lead with: the repo picture, the choice set, or the recommended workstream. Not every mode needs a style; copilot's `pi/workstreams` tool contracts live in the tool descriptions, and the mode file keeps only the facts no single tool description can assert.

## Skill lifecycle language

Prompt fragments distinguish loading a skill from applying it:

- **Load** means call `skill(...)` to add full instructions to the current agent's active context.
- **Apply** means follow instructions already present in that context.

The `skill` tool description owns the reuse/reload policy. Shipped fragments should tell agents to apply relevant skills and reserve load language for missing instructions. A new turn or task is not itself a reason to reload; context loss and intentional refresh are.

Thin action prompt commands are a deliberate exception. `/code-review [additional instructions]` and `/pull-request [additional instructions]` are primary-only entry points that unconditionally direct the agent to load and apply their matching model-invocable skills, passing any arguments as additional instructions. The prompts own routing only; the skills remain the authoritative guidance.

## Defaults and user overrides

Under `defaults/`, a subdirectory is a set you select one member from; a top-level file is not selectable; it loads by rule rather than by choice. The tier is about selectability, not unconditionality: `craft.md` and `environment.md` do load always, but `voice.md` is top-level and still skips personas.

`loadPromptFile` / `loadWorkingStyle` read the user dir first (`~/.pi/basecamp/prompts` · `.../styles`), then fall back to `defaults/`. Override paths follow the same tier: `~/.pi/basecamp/prompts/voice.md` and `~/.pi/basecamp/prompts/craft.md` override the top-level fragments; `~/.pi/basecamp/styles/{name}.md` overrides or adds a working style.

`voice.md` is an adaptation of [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd); the upstream copyright and MIT permission notice are in the repo-root `NOTICE`.

## Registration

Registered in `extension.ts` immediately after `workspace`. Because it binds at `before_agent_start` (which fires after every `session_start`), registration order is not load-bearing: it reads whatever workspace and project state resolved during session start.

## Dependencies

- **core** (`#core/*`): `agent-mode` (+ the `isCopilotMode` predicate), `catalog`, `#core/project` (project state · context-file loader · repo-logseq), `#core/workspace` (workspace state), host paths.
