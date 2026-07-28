# system-prompt

The context/prompt layer — assembles the replacement system prompt on every agent start.

Basecamp fully *replaces* pi's default system prompt rather than appending to it, so this domain must provide everything: environment, working style, project context, and the tool/skill/agent index. It binds `before_agent_start`, builds the prompt, and returns it.

## Architecture: 6 categories, 9 blocks

The prompt is assembled from blocks grouped into categories, in this order:

| # | Category | Block | Source | Included when |
|---|----------|-------|--------|---------------|
| 1 | Constraints | read-only | `defaults/modes/read-only.md` | `--read-only` |
| 2 | Posture | mode | `defaults/modes/{analysis,planning,work,copilot}.md` | primary session |
| 3 | | persona | `#core/swarm` `builtin/*.md` (via `agentPrompt`) | dispatched agent |
| 4 | Style | role style | `defaults/styles/{engineering,advisor,logseq}.md` | user-facing, non-copilot |
| 5 | | voice | `defaults/voice.md` | primary session |
| 6 | | craft | `defaults/craft.md` | **always** |
| 7 | Capabilities | index | `buildCapabilitiesIndex` | always |
| 8 | Project | repo context · repo memory | `buildProjectContext` · `buildRepoLogseqContext` | always · copilot |
| 9 | Environment | session facts · runtime | `defaults/environment.md` · `buildEnvBlock` | always |

Two structural rules keep it from re-accreting.

### Ownership rule — one question per layer

Each layer answers exactly one question. When guidance appears in the wrong layer it gets duplicated, because the layer that should own it still needs it.

| Layer | Answers |
|-------|---------|
| `environment.md` | What is true here? (machine, sandbox, guards, tooling) |
| `buildEnvBlock` | What is true right now? (cwd, repo, worktree, date) |
| tool description | How do I call this? |
| `modes/*` | **What are we doing?** |
| `styles/*` | **How are things achieved?** — who you are and how you work (selectable role) |
| `voice.md` | **How is output shaped?** (any primary session) |
| `craft.md` | **How is code written?** (unconditional) |
| skills | How do I do this well, in depth? |
| project context | What's non-obvious about this repo? |

Mode and style are the *what* and the *how* of a session. Test a fragment by asking which it is: "you implement and integrate" is a what (mode); "you are a partner, not a follower" is a how (style). Where a rule belongs to voice's question — how output is shaped — voice owns it and the role styles do not repeat it: the no-estimates rule was stated in both `engineering.md` and `logseq.md` until `voice.md` claimed it, and each rule is now asserted exactly once.

Consequences worth stating, because each was a live duplication:

- **Tool mechanics never go in a prompt fragment.** `buildCapabilitiesIndex` injects every registered tool description verbatim, so restating a calling contract in a fragment presents it twice in one prompt. Put the contract in the tool description; keep only policy a tool cannot assert (for example "always maintain tasks") in the style.
- **Cross-tool sequencing goes in a skill**, not a fragment — no single tool description owns a multi-tool workflow. The `workstreams` skill is the worked example.
- **Machine facts stay in `environment.md`, even when a skill covers the topic.** Python/uv lives here; `python-development` owns how to write good Python.
- **Taste never goes in `environment.md`.** Facts are not preferences.

### Consumer-divergence test — when a block is justified

A block boundary is only worth having if two consumers actually disagree about it. If every consumer takes two blocks together, they are one block. The real consumer list is: primary × mode, `worker`, report personas, and read-only variants.

This test is what keeps the block count at 9 rather than ~69. An earlier semantic decomposition (every topic shift becoming a block with an id, condition, and predicate) was rejected: it converts authored prose into config, which is harder to read and makes the assembled prompt harder to reason about.

Applying the test today yields one non-obvious seam: **craft**. It is the only content where a persona and a primary agree while other consumers diverge — `worker` needs the code rubric, report personas and analysis sessions arguably do not. Craft is nonetheless included **unconditionally**, because a gap in coverage is worse than the tokens.

The three Style blocks are a worked example of the test, because each adjacent pair genuinely diverges:

| Block | Consumers | Diverges from the next because |
|---|---|---|
| role style | user-facing, non-copilot | copilot takes voice but loads no role style |
| voice | any primary session | a persona's reader is not a user reading a conversation |
| craft | every consumer, personas included | a persona still writes code |

Voice was **not** shipped unconditionally, and the reason is the test itself. Voice's rules presuppose a human reader in a conversation; for a report persona the reader is the primary agent parsing one artifact, and the persona's own template already mandates that artifact's shape — `general-reviewer` and `security-specialist` end on `### Summary`, `devils-advocate` on `### Bottom Line`, `scout` opens with a restated objective, `worker` owes one final PR-style summary. Voice contradicts every one of those, and it loads *after* the persona block, so on recency it would win. The sharpest failure was silent: a reviewer holding eight findings, told to prefer five ranked items and to name exactly one next step, has two independent pressures to truncate its findings list — a correctness regression in the review product that nobody would observe. Personas are therefore excluded, which is what makes voice a real block rather than a second unconditional file that every consumer takes together with craft.

Voice earned its own block over the alternatives. A **toggleable skill** (basecamp supports `disable-model-invocation: true` + `/skill:` invocation; `code-review` uses it) was rejected because always-on is the point, and output shape is style content, not skill content. A **peer `working_style`** was rejected because `working_style` is single-select, so choosing it would discard the engineer role, task tracking, and git workflow. A **`defaults/rubrics/` directory** grouping craft + voice was rejected because "rubric" is a content genre these two do not share (craft is a standard code is measured against; voice is how output is shaped) — their only shared property is being always-loaded, which is what the top-level tier already names. **Promoting the always-on fragments to a 7th category** was rejected: categories are a reading aid over blocks, and the divergence test governs blocks, so categories stay at 6.

The rule set is built on two claims about a reader in a terminal: what is not on screen is forgotten, and knowing the answer is not the same as doing it. That is the test for adding a voice rule — it should serve one of those, or it is taste. The claims are stated here rather than in `voice.md` because every rule there already carries its own motivation at the point of use ("the user cannot carry 'step 3 of 5' between messages, so say it"), and a preamble restating them would ship the same reasoning twice in one prompt.

`voice.md` is an adaptation, not a copy, of [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd) (MIT). Two upstream rules were deliberately dropped: the time-estimate rule, because it contradicts basecamp's no-estimates stance; and destructive-action confirmation, because `environment.md` already owns it and voice's framing implied model discretion where the real mechanism is an enforced reviewer gate. Rules that another always-loaded fragment or a role style already asserts stay out — a fragment that restates its neighbours teaches the model that all of it is advisory.

### Generator vs. authored

The category boundary encodes this split. Constraints, Posture, and Style are **authored prose** in `defaults/` (user-overridable). Capabilities, Project, and the runtime half of Environment are **generated** from runtime state. Do not interpolate authored prose into a generator, and do not hand-maintain in prose what a generator can derive.

Prompt-block ordering is chosen for coherence rather than positional emphasis: this model generation does not weight end-of-context instructions more heavily, which is what previously justified scattering related content.

## What it does

- **`prompt.ts`** — the `before_agent_start` hook + `assemblePrompt`, plus the file loaders and their user-override fallback.
- **`context-builders.ts`** — pure fragment builders: worktree warning, unsafe-edit guidance, project-context block, capabilities index.
- **`defaults/`** — the shipped fragments: the always-loaded top-level files (`environment.md`, `voice.md`, `craft.md`) and the selectable sets `modes/<mode>.md`, `styles/<style>.md`.

### Copilot is a mode that carries its own manner

Copilot is a distinct *activity* — orient the repo, make the choice set clear, shape and stage workstreams, curate repo memory — so it is a mode, not a style. It is also the one mode that loads **no** style file, because no selectable style fits: `engineering` asserts "you implement directly" and copilot does not implement; `advisor` drags prose-over-bullets and a research section; `logseq` assumes cwd is the graph root. The one style block it does load is voice, which reaches every primary session regardless of mode, so its output shape needs no inline repetition.

What remains inline is a short "Work with the user" section that names which artifact to lead with — the repo picture, the choice set, or the recommended workstream. That reads as mode content (a *what*, not a *how*), but the residue is small enough that the line is honestly arguable: it sits inside the mode because a single-purpose `styles/copilot.md` would hold ~50 words that only copilot ever loads, so the **consumer-divergence test rejects it** — the boundary would add no composition, only taxonomy. When ownership and divergence conflict, divergence wins: it is about composition value, ownership only about tidiness. Not every mode needs a style.

The `copilot` mode is load-bearing beyond prose: `isCopilotMode` suppresses the style, hides `plan` from the capabilities index, hard-blocks the `plan` tool call in `#tasks`, and locks shift+tab. Do not remove it.

Because copilot is launch-only and immutable, capabilities can be scoped by **gating registration** rather than filtering the index — see `pi/workstreams/index.ts`. The gating predicate must also be resolvable at extension-load time, which is why copilot-launch reads `process.argv` rather than `pi.getFlag`: Pi applies flag values only after extensions activate. An unregistered tool can never become callable mid-session, so unlike `plan` it needs no call-time block.

The workstream **tool contracts live in the tool descriptions**, which the index already injects; `modes/copilot.md` keeps only the handful of facts no single tool description can assert (list before create, an edit does not reach a running session, launching is not starting, cross-repo launch, pull-based handles). A `workstreams` skill was tried and removed: ~320 of its 422 words restated those descriptions, and the ~100 that remained were too few to justify a file the copilot would have to load in every session.

## Skill lifecycle language

Prompt fragments distinguish loading a skill from applying it:

- **Load** means call `skill(...)` to add full instructions to the current agent's active context.
- **Apply** means follow instructions already present in that context.

The `skill` tool description owns the reuse/reload policy. Shipped fragments should tell agents to apply relevant skills and reserve load language for missing instructions. A new turn or task is not itself a reason to reload; context loss and intentional refresh are.

## Defaults ↔ user override

Under `defaults/`, a subdirectory is a set you select from; a top-level file is always loaded. `environment.md` was the precedent; `voice.md` and `craft.md` now follow it. The rule is load-bearing, not cosmetic: Python resolves available working styles by globbing `defaults/styles/*.md` (in `src/basecamp/config_cli/project.py` and `src/basecamp/core/doctor/checks/references.py`), so while `craft.md` sat in `styles/` it was wrongly offered as a selectable `working_style` and wrongly validated by `basecamp doctor`. The move fixed that with no code change and no exclusion list, and left `loadWorkingStyle()` with exactly one caller — the role style.

`loadPromptFile` / `loadWorkingStyle` read the user dir first (`~/.pi/basecamp/prompts` · `.../styles`), then fall back to `defaults/`. Override paths follow the same tier: `~/.pi/basecamp/prompts/voice.md` and `~/.pi/basecamp/prompts/craft.md` override the always-on fragments; `~/.pi/basecamp/styles/{name}.md` overrides or adds a working style. No migration moved a craft override from `styles/` to `prompts/` — the styles dir was scaffolded empty by `basecamp setup`, so nothing broke.

## Registration

Registered in `extension.ts` immediately after `workspace`. Because it binds at `before_agent_start` — which fires after every `session_start` — registration order is not load-bearing: it reads whatever workspace and project state resolved during session start.

## Dependencies

- **core** (`#core/*`): `agent-mode` (+ the `isCopilotMode` predicate), `catalog`, `#core/project` (project state · context-file loader · repo-logseq), `#core/workspace` (workspace state), host paths.
