# system-prompt

The context/prompt layer — assembles the replacement system prompt on every agent start.

Basecamp fully *replaces* pi's default system prompt rather than appending to it, so this domain must provide everything: environment, working style, project context, and the tool/skill/agent index. It binds `before_agent_start`, builds the prompt, and returns it.

## Architecture: 6 categories, 8 blocks

The prompt is assembled from blocks grouped into categories, in this order:

| # | Category | Block | Source | Included when |
|---|----------|-------|--------|---------------|
| 1 | Constraints | read-only | `defaults/modes/read-only.md` | `--read-only` |
| 2 | Posture | mode | `defaults/modes/{analysis,planning,work,copilot}.md` | primary session |
| 3 | | persona | `#core/swarm` `builtin/*.md` (via `agentPrompt`) | dispatched agent |
| 4 | Style | style | `defaults/styles/{engineering,advisor,logseq}.md` | user-facing, non-copilot |
| 5 | | craft | `defaults/styles/craft.md` | **always** |
| 6 | Capabilities | index | `buildCapabilitiesIndex` | always |
| 7 | Project | repo context · repo memory | `buildProjectContext` · `buildRepoLogseqContext` | always · copilot |
| 8 | Environment | session facts · runtime | `defaults/environment.md` · `buildEnvBlock` | always |

Two structural rules keep it from re-accreting.

### Ownership rule — one question per layer

Each layer answers exactly one question. When guidance appears in the wrong layer it gets duplicated, because the layer that should own it still needs it.

| Layer | Answers |
|-------|---------|
| `environment.md` | What is true here? (machine, sandbox, guards, tooling) |
| `buildEnvBlock` | What is true right now? (cwd, repo, worktree, date) |
| tool description | How do I call this? |
| `modes/*` | **What are we doing?** |
| `styles/*` | **How are things achieved?** |
| skills | How do I do this well, in depth? |
| project context | What's non-obvious about this repo? |

Mode and style are the *what* and the *how* of a session. Test a fragment by asking which it is: "you implement and integrate" is a what (mode); "you are a partner, not a follower" is a how (style).

Consequences worth stating, because each was a live duplication:

- **Tool mechanics never go in a prompt fragment.** `buildCapabilitiesIndex` injects every registered tool description verbatim, so restating a calling contract in a fragment presents it twice in one prompt. Put the contract in the tool description; keep only policy a tool cannot assert (for example "always maintain tasks") in the style.
- **Cross-tool sequencing goes in a skill**, not a fragment — no single tool description owns a multi-tool workflow. The `workstreams` skill is the worked example.
- **Machine facts stay in `environment.md`, even when a skill covers the topic.** Python/uv lives here; `python-development` owns how to write good Python.
- **Taste never goes in `environment.md`.** Facts are not preferences.

### Consumer-divergence test — when a block is justified

A block boundary is only worth having if two consumers actually disagree about it. If every consumer takes two blocks together, they are one block. The real consumer list is: primary × mode, `worker`, report personas, and read-only variants.

This test is what keeps the block count at 8 rather than ~69. An earlier semantic decomposition (every topic shift becoming a block with an id, condition, and predicate) was rejected: it converts authored prose into config, which is harder to read and makes the assembled prompt harder to reason about.

Applying the test today yields exactly one non-obvious seam: **craft**. It is the only content where a persona and a primary agree while other consumers diverge — `worker` needs the code rubric, report personas and analysis sessions arguably do not. Craft is nonetheless included **unconditionally**, because a gap in coverage is worse than the tokens and it removes every remaining conditional from the matrix.

### Generator vs. authored

The category boundary encodes this split. Constraints, Posture, and Style are **authored prose** in `defaults/` (user-overridable). Capabilities, Project, and the runtime half of Environment are **generated** from runtime state. Do not interpolate authored prose into a generator, and do not hand-maintain in prose what a generator can derive.

Prompt-block ordering is chosen for coherence rather than positional emphasis: this model generation does not weight end-of-context instructions more heavily, which is what previously justified scattering related content.

## What it does

- **`prompt.ts`** — the `before_agent_start` hook + `assemblePrompt`, plus the file loaders and their user-override fallback.
- **`context-builders.ts`** — pure fragment builders: worktree warning, unsafe-edit guidance, project-context block, capabilities index.
- **`defaults/`** — the shipped fragments: `environment.md`, `modes/<mode>.md`, `styles/<style>.md`.

### Copilot is a mode that carries its own manner

Copilot is a distinct *activity* — orient the repo, make the choice set clear, shape and stage workstreams, curate repo memory — so it is a mode, not a style. It is also the one mode that loads **no** style file: it carries its short "Work with the user" section inline instead.

That looks like an ownership-rule violation (a *how* inside a *what*), and it is a deliberate one. No existing style fits: `engineering` asserts "you implement directly" and copilot does not implement; `advisor` drags prose-over-bullets and a research section; `logseq` assumes cwd is the graph root. A single-purpose `styles/copilot.md` would hold ~50 words that only copilot ever loads, so the **consumer-divergence test rejects it** — the boundary would add no composition, only taxonomy. When ownership and divergence conflict, divergence wins: it is about composition value, ownership only about tidiness. Not every mode needs a style.

The `copilot` mode is load-bearing beyond prose: `isCopilotMode` suppresses the style, hides `plan` from the capabilities index, hard-blocks the `plan` tool call in `#tasks`, and locks shift+tab. Do not remove it.

Because copilot is launch-only and immutable, capabilities can be scoped by **gating registration** rather than filtering the index — see `pi/workstreams/index.ts`. An unregistered tool can never become callable mid-session, so unlike `plan` it needs no call-time block.

The workstream **tool contracts live in the tool descriptions**, which the index already injects; `modes/copilot.md` keeps only the handful of facts no single tool description can assert (list before create, an edit does not reach a running session, launching is not starting, cross-repo launch, pull-based handles). A `workstreams` skill was tried and removed: ~320 of its 422 words restated those descriptions, and the ~100 that remained were too few to justify a file the copilot would have to load in every session.

## Skill lifecycle language

Prompt fragments distinguish loading a skill from applying it:

- **Load** means call `skill(...)` to add full instructions to the current agent's active context.
- **Apply** means follow instructions already present in that context.

The `skill` tool description owns the reuse/reload policy. Shipped fragments should tell agents to apply relevant skills and reserve load language for missing instructions. A new turn or task is not itself a reason to reload; context loss and intentional refresh are.

## Defaults ↔ user override

`loadPromptFile` / `loadWorkingStyle` read the user dir first (`~/.pi/basecamp/prompts` · `.../styles`), then fall back to `defaults/`. Because craft is a style file, `~/.pi/basecamp/styles/craft.md` overrides the shipped rubric.

## Registration

Registered in `extension.ts` immediately after `workspace`. Because it binds at `before_agent_start` — which fires after every `session_start` — registration order is not load-bearing: it reads whatever workspace and project state resolved during session start.

## Dependencies

- **core** (`#core/*`): `agent-mode` (+ the `isCopilotMode` predicate), `catalog`, `#core/project` (project state · context-file loader · repo-logseq), `#core/workspace` (workspace state), host paths.
