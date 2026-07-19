# Review instructions

You are an **independent counter-check**, not a co-author. Your job is to **try
to disprove the change**, not to confirm it. Treat the PR description and code
comments as *claims, not evidence*: verify against the actual code. Plausible,
confident-looking changes are exactly where subtle bugs hide — and in basecamp
the dangerous ones fail *silently* (a hook that blocks a session instead of
failing open, a daemon frame the store can't parse, a `session_start` that
re-registers on resume) rather than crashing. A clean review means "I could not
break this," never "this is correct."

## How to report

Write every finding to be self-contained and specific enough to act on without a
follow-up:

- Anchor to `file:line`.
- State the **concrete input, state, or sequence that breaks it** — not a general
  worry. For lifecycle bugs, name the exact trigger: session resume, `/clear`,
  compaction, subagent stop, daemon respawn after a protocol bump.
- Give a one-line **direction for the fix**.
- Behavior claims need a `file:line` citation in the source, not an inference
  from naming. Prefer fewer, higher-confidence findings over speculation.

Post each finding as an inline comment on the exact line. When a finding turns on
a lifecycle, **spell out the sequence** so it's auditable at a glance, e.g.
`SessionStart on resume → handler doesn't no-op → duplicate sessions row ✗`.

Open the summary with a one-line tally (e.g. `1 important, 2 nits`), and lead
with "No blocking issues" when there are none. End the summary with one line
naming what you did **not** verify (e.g. "Not checked: the docker harness, the
MCP resource rendering") so silence is never mistaken for coverage.

## Severity

- 🔴 **Important** — would break a live session, corrupt coordination state, or
  desync a client from the daemon: a hook that can block or crash a session
  instead of failing open, the file-length hook made blocking (a `decision`
  field), a daemon route/body changed without the matching `CLAUDE_PROTOCOL_VERSION`
  bump, non-additive store DDL (an `ALTER` or a narrowed `CREATE`), a `config.json`
  write outside the Python `Settings` writer, a `session_start` that re-registers
  on resume/reload/fork, a workstream write that overwrites instead of appending.
  Merge-blocking.
- 🟡 **Nit** — everything else. Cap at five per review; if you found more, give a
  count in the summary instead of posting them all. If all you found are nits,
  lead with "No blocking issues."

## Don't re-flag what CI already guarantees

`.github/workflows/ci.yml` — ruff lint, ruff format, and pytest — already
enforces the left column. Do **not** spend findings there; spend them on the
right column, which no check covers:

| CI already owns (skip) | Focus here (unguarded) |
|---|---|
| ruff lint + format (Python) | a hook that can raise past its fail-open guard, or block a session it should only warn on |
| pytest green | logic the tests don't exercise; a daemon contract changed on only one side (route/body vs. `CLAUDE_PROTOCOL_VERSION` vs. store) |
| — (no file-length gate) | a source file over the 500-line cap not split along a real responsibility seam (`-part2` / style-compression instead) |

## Plugin & backend integrity (the spine — scrutinize every change that touches it)

- **Hooks are strictly fail-open; the file-length hook is non-blocking.**
  `basecamp-hook <event>` must always exit 0 — any failure (daemon down,
  malformed payload, unexpected error) degrades to no output, never a block
  (`hooks/__init__.py`). The `PostToolUse` file-length handler must stay a pure
  advisory: it emits `hookSpecificOutput.additionalContext` with **no `decision`
  field**, and the write always stands (`hooks/file_length.py`). **Flag** a hook
  path that can raise past the fail-open guard, an event that returns a blocking
  `decision`/exit-2, or a file-length change that denies the tool or prompts the
  user.
- **Session lifecycle handlers must no-op on the wrong shape.** `handle_session_start`
  skips subagents and a missing/blank/non-string `session_id`; `handle_pre_compact`
  and `handle_subagent_stop` likewise skip subagents / missing ids; `handle_session_end`
  ingests the transcript **before** closing the episode so tail nodes are tagged
  with the ending episode (`hooks/session.py`). **Flag** a handler that registers
  a subagent as a session, re-registers on resume, or closes the episode before
  ingesting.
- **The hub wire contract is versioned; the store never `ALTER`s.** A route or
  request/response body added or reshaped in `hub/claude/routes.py` /
  `contract.py` without bumping `CLAUDE_PROTOCOL_VERSION` leaves a stale daemon
  accepting the call and silently ignoring the new fields — the health gate can't
  respawn it. The store has no migration mechanism: tables are created once,
  fully-formed (`hub/claude/store/`), so a new column must ship in the same commit
  that introduces its table. **Flag** a one-sided contract change, a missing
  version bump, an `ALTER TABLE`, or a `CREATE TABLE IF NOT EXISTS` narrowed
  relative to a shipped schema.
- **Basecamp (Python) is the sole writer of `~/.pi/basecamp/config.json`.**
  Every config change persists through `basecamp config …` (the flock'd `Settings`
  writer); readers (the MCP server, the launcher) only read. **Flag** any code
  that opens and writes `config.json` directly.
- **Git is the source of truth for worktrees; identity is `<org>/<name>`.**
  basecamp reads git and keeps **no** parallel worktree registry; paths follow
  `~/.worktrees/<org>/<name>/<label>/` and `worktrees_root` is single-sourced in
  `basecamp.claude.paths`. **Flag** the reintroduction of a metadata registry, a
  worktree path off that layout, or code that treats the canonical `<org>/<name>`
  as a worktree label.
- **Workstream attachment is additive.** A session attaches by appending a
  `workstream_sessions` row — never overwriting; liveness derives from the open
  `episodes` row, not a stored status. **Flag** an attach that overwrites, or a
  liveness signal duplicated into a stored field.
- **MCP injected text is a clean, bounded router.** `instructions` is ~2KB and
  truncated, so it must stay a pointer (project identity + a resource pointer),
  never the payload; the bulk lives in resources. The text the server injects must
  read as native project guidance — project facts and pointers, not basecamp
  runtime jargon. **Flag** a bloated `instructions` payload or model-facing text
  that leaks tool-internal framing.
- **Prompt delivery: doctrine reaches subagents, `--system-prompt` does not.**
  Durable guidance that must reach subagents belongs in `claude/prompts/doctrine.md`
  (installed into the home `~/.claude/CLAUDE.md` block by `basecamp install`);
  `bcc`'s `--system-prompt` is main-session-only. **Flag** subagent-critical
  guidance placed only in the launcher's system prompt.
- **The installer is `install_dir`-based and re-runnable; it never re-derives the
  repo from `__file__` at runtime.** `execute_install` (`install.py`) keys every
  step off the recorded `install_dir`, so `basecamp install` works from the
  non-editable installed tool; only the `run_bootstrap` step (from the checkout)
  may use `Path(__file__)`. Plugin registration shells out to the `claude` CLI
  (`plugin marketplace add` + `plugin install`, `claude/plugin.py`) — writing
  `~/.claude/settings.json` alone does **not** load a plugin, since the loader
  reads the `~/.claude/plugins/` cache that `plugin install` builds. The installer
  is fail-soft: a missing `claude` CLI or a failed registration warns and skips,
  never aborting doctrine/config wiring. **Flag** an installer path that derives
  the repo from `__file__` outside the bootstrap, a registration made a hard
  prerequisite (aborting the rest on failure), or a claim that settings.json alone
  loads the plugin.
