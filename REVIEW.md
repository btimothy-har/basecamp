# Review instructions

You are an **independent counter-check**, not a co-author. Your job is to **try
to disprove the change**, not to confirm it. Treat the PR description and code
comments as *claims, not evidence*: verify against the actual code. Plausible,
confident-looking changes are exactly where subtle bugs hide — and in basecamp
the dangerous ones fail *silently* (state that vanishes on `/reload`, a tool the
prompt never surfaces, a frame the daemon can't parse) rather than crashing. A
clean review means "I could not break this," never "this is correct."

## How to report

Write every finding to be self-contained and specific enough to act on without a
follow-up:

- Anchor to `file:line`.
- State the **concrete input, state, or sequence that breaks it** — not a general
  worry. For lifecycle bugs, name the exact trigger: `/reload`, session resume,
  `--copilot` launch, subagent dispatch, daemon reconnect.
- Give a one-line **direction for the fix**.
- Behavior claims need a `file:line` citation in the source, not an inference
  from naming. Prefer fewer, higher-confidence findings over speculation.

Post each finding as an inline comment on the exact line. When a finding turns on
a lifecycle, **spell out the sequence** so it's auditable at a glance, e.g.
`launch → /reload re-imports module → module-scoped Map is empty → active worktree lost ✗`.

Open the summary with a one-line tally (e.g. `1 important, 2 nits`), and lead
with "No blocking issues" when there are none. End the summary with one line
naming what you did **not** verify (e.g. "Not checked: Python daemon side of the
protocol change, tmux pane teardown") so silence is never mistaken for coverage.

## Severity

- 🔴 **Important** — would break the live session or corrupt coordination state:
  surviving state kept as plain module state (lost on `/reload`), a tool that must
  be hidden in copilot left reachable, a hub frame the daemon can't parse, a
  `config.json` write outside the Python writer, a dispatched subagent that loses
  its `BASECAMP_*` identity, a `session_start` that re-injects on resume/reload.
  Merge-blocking.
- 🟡 **Nit** — everything else. Cap at five per review; if you found more, give a
  count in the summary instead of posting them all. If all you found are nits,
  lead with "No blocking issues."

## Don't re-flag what CI already guarantees

`.github/workflows/ci.yml` — ruff, tsc, biome, the import-boundary and
file-length scripts, and both test suites — already enforces the left column.
Do **not** spend findings there; spend them on the right column, which no check
covers:

| CI already owns (skip) | Focus here (unguarded) |
|---|---|
| ruff lint + format (Python) | live-session state lost on `/reload` — surviving state must use `processScoped`, not module state |
| tsc types, biome lint | a new tool / skill / env fact the fully-replaced system prompt never surfaces to the agent |
| import boundaries (`#<domain>/index.ts` only; core imports no domain) | a boundary-legal import that still inverts layering or teaches core a feature |
| file-length caps (.ts ≤ 350, .py ≤ 500) | a cap "met" by style-compression or a `-part2` file instead of a real responsibility split |
| whole-graph load + registration (`extension.test.ts`) | a new domain not wired into the composition root, the `npm test` glob, or the boundary CONTEXTS list |
| pytest + npm test green | logic the tests don't exercise; a TS↔Python contract changed on only one side |

## Extension integrity (the spine — scrutinize every change that touches it)

- **Surviving state must outlive `/reload`; wiring must not pretend to.**
  `/reload` re-imports the extension with fresh module instances, so any live
  value that must persist — session state, agent mode, invoked skills, workspace
  runtime, the daemon socket — has to go through `processScoped(key, init)`
  (`pi/core/global-registry.ts`) with a **stable** key string. **Flag** new
  surviving state kept in a module-level `let`/`Map`/`const` (silently reset on
  reload), and any change to an existing `processScoped` key (breaks restoration
  across releases — the prior state is orphaned). Conversely, don't push plain
  wiring the composition root rebuilds every load into `processScoped`.
- **The system prompt is fully replaced, not appended** (`pi/system-prompt/`).
  Nothing from Pi's default prompt reaches the agent unless basecamp assembles it.
  **Flag** a new tool, slash command, or skill the agent is expected to use that
  never flows into the prompt via `getAllTools()`/`getCommands()`, and any change
  that assumes Pi still supplies environment or tool guidance the replaced prompt
  now owns.
- **Copilot is a locked, `plan()`-free mode**, and that guarantee lives in layers
  that must stay in lockstep. `copilot` must remain excluded from
  `CYCLEABLE_AGENT_MODES` so shift+tab (`cycleAgentMode`) can neither enter nor
  leave it (`pi/core/agent-mode/index.ts`). `plan()` is hidden by the paired
  `isCopilotMode` / `PLAN_TOOL_NAME` predicate (`pi/core/agent-mode/copilot.ts`),
  enforced in **both** the tasks `tool_call` block and the workspace
  capabilities-index filter. **Flag** a change that makes copilot cyclable, exposes
  `plan()` (or a new plan-like tool) in copilot, or updates only one of the two
  enforcement layers.
- **Basecamp (Python) is the sole writer of `~/.pi/basecamp/config.json`; Pi reads
  it in-process.** The `/model-aliases` TUI and every other Pi-side config change
  persist by shelling out to `basecamp config …` (the flock'd `Settings` writer),
  never by writing the file directly. **Flag** any TS/Pi code that opens and writes
  `config.json` itself (`pi/core/model/aliases.ts` is the read-side reference).
- **The hub wire protocol is a TS↔Python contract** (`pi/core/hub/protocol/`,
  `PROTOCOL_VERSION` in `protocol/version.ts`). A frame added or reshaped on the TS
  side without the matching change in the Python daemon (`src/basecamp/hub/`) — or
  a `PROTOCOL_VERSION` bump on one side only — desyncs every session from the
  daemon. **Flag** one-sided frame or version changes, and shared fixtures updated
  on only one side.
- **Git is the source of truth for worktrees; identity is `<org>/<name>`.**
  Basecamp reads `git worktree list --porcelain` and keeps **no** parallel metadata
  registry. **Flag** the reintroduction of such a registry, a worktree path that
  doesn't follow `~/.worktrees/<org>/<name>/<label>/`, and any code that treats
  `BASECAMP_REPO` (the canonical `<org>/<name>`) as a worktree label. A dispatched
  subagent inherits `BASECAMP_*` via `process.env` — flag a launch path that drops
  or mis-sets that chain, and any secret or token written to logs.
- **Workstream coordination is additive and fresh-session-only.** Every
  `pi --workstream` session **appends** a `workstream_agents` row — it never
  overwrites — and the `session_start` handler must no-op once the conversation
  already has turns, so resume/reload/fork/compact never re-attach or re-inject the
  brief (`pi/workstreams/`). **Flag** a write that overwrites agent rows instead of
  appending, and any `session_start` path that re-injects on a non-fresh session.
