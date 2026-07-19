# AGENTS.md

## What is basecamp

A project-aware **Claude Code plugin** for AI coding agents, backed by a Python
distribution. It injects each project's related directories and curated context
into the session, ships engineering skills and a copilot workflow, drives the
session lifecycle through fail-open hooks, and persists coordination state
(sessions, episodes, transcripts, workstreams) in a host-global daemon.

basecamp standardizes on Claude Code as its single runtime (decision record:
`docs/design/claude-code-compatibility.md`). It was previously a Pi extension;
that TypeScript extension and its WebSocket swarm daemon / companion TUI have
been removed. What remains is the Claude plugin (`claude/`) and the Python that
serves it (`src/basecamp/`).

The repo ships **two intertwined artifacts**:

| Artifact | Directory | Purpose |
|----------|-----------|---------|
| The Claude Code plugin | `claude/` | The container Claude Code loads: plugin manifest, MCP config, hooks, prompts, skills, shims, docker |
| The `basecamp` Python distribution | `src/basecamp/` | One src-layout package: the CLI/launcher plus the `mcp`, `hooks`, `claude`, `hub.claude`, `core`, and `workspace` subpackages the plugin's shims exec |

The plugin's `bin/` shims (`basecamp-mcp`, `basecamp-hook`) exec the matching
Python console script from the `basecamp` install, so the plugin is a thin native
shell over the Python backend.

## Repo Map

```
pyproject.toml  uv.lock  install.py  Makefile   # Python toolchain + bootstrap
docs/  tests/  migrations/                       # design records; pytest suites (tests/<domain>/); one-shot state migration

claude/                            # ① the Claude Code plugin
├── .claude-plugin/plugin.json      # plugin manifest (name/version; namespaces skills as /basecamp:<name>)
├── .mcp.json                       # registers the stdio MCP context server (→ bin/basecamp-mcp)
├── hooks/hooks.json                # SessionStart/End · PreCompact · SubagentStop · PostToolUse → bin/basecamp-hook <event>
├── bin/                            # POSIX-sh shims: basecamp-mcp, basecamp-hook (exec the console script from the basecamp install)
├── prompts/                        # system-prompt.md (bcc --system-prompt, main-only) · doctrine.md (shared engineering doctrine → home CLAUDE.md)
├── skills/                         # native skills: python-development · sql · data-warehousing · data-analysis · marimo · gather · planning · pr · copilot · start-workstream
├── docker/                         # sandboxed plugin-lifecycle harness (Dockerfile, entrypoint, bc-inspect)
└── README.md                       # the plugin's own design record (static-vs-dynamic homes, tier rollout)

src/basecamp/                      # ② the basecamp Python package
├── cli.py                          # Click entry point: install · claude launch · hub · config (group) · workstream (group)
├── install.py                      # the installer: run_bootstrap (uv tool install + record install_dir) + execute_install (register plugin, doctrine, config)
├── claude/                         # the `bcc` launcher + plugin registration: builds the per-session --system-prompt and execs `claude`
│                                   #   config · gitutil · herdr · identity · launch · logseq · naming · paths · plugin · worktree
├── hooks/                          # strictly fail-open Claude Code hooks: __init__ (dispatch) · session (lifecycle) · file_length (PostToolUse warn)
├── mcp/                            # the stdio MCP context server: server · resolve · render · tools/workstreams
├── hub/claude/                     # the session hub daemon (HTTP-over-UDS): server · app · routes · contract · ingest · transcript · sidecars
│                                   #   store/ (sessions · episodes · transcripts · workstreams) · client/ (transport · sessions · workstreams · spawn · identity)
├── core/                           # settings · paths · files · exceptions · projects · directories · model_aliases · cli/ (unified config.json plumbing + porcelain + workstream group)
└── workspace/                      # per-repo worktree-setup `environments` config + its menus (cli/, ui)
```

`basecamp` is one ordinary src-layout package under `src/basecamp/` —
`import basecamp.<domain>` resolves to `src/basecamp/<domain>/`.

Console scripts (`pyproject [project.scripts]`):

| Script | Target | Role |
|--------|--------|------|
| `basecamp` | `basecamp.cli:main` | the CLI (install, config, workstream, hub, claude launch) |
| `bcc` | `basecamp.claude.launch:main` | launch `claude` with the basecamp system prompt (same as `basecamp claude launch`) |
| `basecamp-mcp` | `basecamp.mcp.server:main` | the stdio MCP context server (spawned by the plugin's `.mcp.json`) |
| `basecamp-hook` | `basecamp.hooks:main` | dispatch a Claude Code hook event (spawned by the plugin's `hooks.json`) |

## Architecture Decisions

### Two delivery channels: the plugin and the Python backend

The plugin (`claude/`) is what Claude Code loads. `basecamp install` registers it
with Claude Code (via the `claude plugin` CLI — see below), so a bare `claude`
auto-loads it; no `--plugin-dir`. It carries only native components plus thin
`bin/` shims. Everything with logic lives in the Python package and is reached
through those shims or the CLI. This keeps the plugin declarative and puts every
testable behavior in `src/basecamp/`.

### Installer surface & plugin auto-registration

The installer is two layered entry points in `src/basecamp/install.py`, both keyed
off a recorded `install_dir` (the repo checkout, in `~/.pi/basecamp/config.json`)
so the wiring works from the non-editable installed tool:

- **`run_bootstrap`** — the chicken-and-egg step (`uv run install.py` /
  `make install`, run from the checkout): `uv tool install` the `basecamp` snapshot
  onto PATH, record the checkout as `install_dir`, then call `execute_install`.
  This is the only step that may derive the repo from `Path(__file__)`.
- **`execute_install`** (`basecamp install`) — everything re-runnable: register the
  plugin, install the home doctrine, scaffold the `context/` dir, seed the default
  config. All `install_dir`-based, so it is safe to re-run from the installed tool.

**Plugin auto-registration** (`src/basecamp/claude/plugin.py`) shells out to the
`claude` CLI — `plugin marketplace add <install_dir>/claude` → `plugin install
basecamp@basecamp` → `marketplace update` → `plugin update` (all idempotent). This
is deliberate: writing `enabledPlugins` / `extraKnownMarketplaces` into
`~/.claude/settings.json` alone does **not** load a plugin — Claude Code's loader
reads the `~/.claude/plugins/` cache that `plugin install` builds. The two `update`
steps refresh that cache from source, so re-running `basecamp install` picks up
plugin edits. Registration is **fail-soft**: a missing `claude` CLI or a failed
command warns and skips rather than aborting the doctrine/config wiring. The
committed `claude/.claude-plugin/marketplace.json` declares `claude/` as the
local single-plugin marketplace that `marketplace add` reads.

### Prompt delivery: two channels, main vs. everywhere

basecamp's prompt content lives in `claude/prompts/` and reaches sessions two ways:

- **`bcc` builds a per-session `--system-prompt`** (`claude/prompts/system-prompt.md`
  assembled in `basecamp.claude.launch`) — dynamic, and applies to the **main
  session only** (Claude Code does not thread `--system-prompt` into subagents).
- **The home doctrine** (`claude/prompts/doctrine.md`) is installed by
  `basecamp install` into a managed block in `~/.claude/CLAUDE.md` — shared
  engineering doctrine that reaches the main session **and every subagent**.

So per-session, main-only guidance goes through the launcher's system prompt;
durable doctrine that must reach subagents goes through the home `CLAUDE.md`.

### MCP context server: awareness via `instructions` + resources

The stdio MCP server (`basecamp.mcp`) injects project awareness natively. Claude
Code injects an MCP server's `instructions` field into the system prompt at
session start (~2KB, truncated), so `instructions` is a **router** (project
identity + a pointer to the resources), never the payload; the bulk — related
directories, curated context, Logseq memory — lands in **MCP resources**. Project
identity and context resolve from the `projects` section of
`~/.pi/basecamp/config.json`, the single source of truth. The MCP tools surface
(`mcp/tools/`) is where workstream orchestration lands (`create_workstream`, …).

### Hooks are strictly fail-open

`basecamp-hook <event>` reads the hook JSON from stdin, dispatches to a handler
(`hooks/__init__.py` `_HANDLERS`), and **always exits 0** — a hook must never
block or fail a session. A handler may return a string, which `main()` writes to
stdout as the hook's JSON response; on any error the hook degrades to no output,
never a block. The `bin/basecamp-hook` shim is itself fail-open (exits 0 with a
stderr note when `basecamp` isn't installed).

Wired events (`claude/hooks/hooks.json`):

- **SessionStart** → register the session with the hub daemon (`sessions` row).
- **SessionEnd** → ingest the final transcript (sweeping every subagent sidecar), then close the session's episode.
- **PreCompact** → ingest the main transcript before Claude Code compacts (compaction is append-only, so this only narrows the loss window).
- **SubagentStop** → ingest the just-finished subagent sidecar promptly.
- **PostToolUse** (`Write|Edit`) → the non-blocking file-length warn (below).

Transcript ingestion design: `docs/design/transcript-ingestion.md`.

### The hub daemon

A host-global, all-Python service (`basecamp hub`) speaking **HTTP over a Unix
domain socket** (`~/.pi/basecamp/claude/daemon.sock`; no WebSocket). It persists
coordination state in SQLite (`~/.pi/basecamp/claude/daemon.db`):

- `sessions` (identity) + `episodes` (liveness) — the session lifecycle.
- `transcript_nodes` — verbatim, uuid-keyed conversation DAG for the main thread and every subagent sidecar (ingest-and-store only; no analysis).
- `workstreams` + `workstream_sessions` — durable, cross-session workstream coordination records.

The wire contract is protocol-versioned (`CLAUDE_PROTOCOL_VERSION` in
`hub/claude/contract.py`); a bump health-gates and respawns a stale daemon. The
store has **no `ALTER`-based migration** — tables are created once, fully-formed;
keep DDL additive. The daemon is self-contained under `hub/claude/` (its own
`store/`) and is spawned/ensured lazily by the client (`hub/claude/client/`).

### File-length cap → doctrine (primary) + a non-blocking warn hook

The line cap is a soft **500 lines** for most code, with a few per-type
exceptions (shell ~400; SQL and HTML ~800). basecamp is Python, so its own cap is
500. The cap is a module-design forcing function: when a file approaches it,
split along responsibility seams into focused modules, never by compressing style
or with `-part2` continuation files.

Enforcement is two layers, with the doctrine as the primary carrier:

1. **The engineering doctrine** (`claude/prompts/doctrine.md`) states the rule
   and its rationale, and reaches the main session **and** subagents via the home
   `~/.claude/CLAUDE.md` block — so the agent learns the expectation before
   writing anything.
2. **A non-blocking PostToolUse warn hook** (`hooks/file_length.py`): after a
   `Write`/`Edit` grows a *source* file past the cap, it emits an advisory
   (`hookSpecificOutput.additionalContext`, no `decision` field) telling the agent
   to review and split. The write **succeeds** — the hook never denies the tool or
   prompts the user; it is a nudge, not a gate. Non-source files (data, lockfiles,
   markdown, config) are exempt.

There is **no CI gate** on file length; enforcement is the doctrine plus the warn.

### Config: Basecamp (Python) is the sole writer

`~/.pi/basecamp/config.json` is the unified config document (projects,
per-repo `environments`, `model_aliases`, installer metadata). Basecamp's Python
`Settings` is the sole writer, guarded by a flock; every config change goes
through `basecamp config …`. Consumers (the MCP server, the launcher) read it.
User context overrides live beside it under `~/.pi/basecamp/context/`.
The Claude launcher foundation additionally reads `~/.claude/basecamp.json`
(`basecamp.claude.config`). (`~/.pi` is legacy naming kept for runtime state; it
is not a Pi dependency.)

### Worktree design

Worktrees live at `~/.worktrees/<org>/<name>/<label>/` — outside the repo, keyed
by the canonical `<org>/<name>` identity (from the origin remote, falling back to
the git basename). Git is the source of truth (`git worktree list --porcelain`);
basecamp keeps no parallel registry. `worktrees_root` is single-sourced in
`basecamp.claude.paths`. Copilot-dispatched workstreams use a `copilot/<slug>`
worktree label paired with a `bt/<slug>`-style branch.

### Workstreams & copilot

Workstreams are durable, repo-neutral coordination records in the hub daemon
(`workstreams` + `workstream_sessions`). Identity is an internal `ws_<uuid>` id
plus a globally-unique three-word `slug`; the record is a **pointer bundle**
(brief + worktree/branch/dossier paths), never the content. Copilot is a native
skill (`claude/skills/copilot/`) guarded to the Herdr environment; it stages work
via `create_workstream` (record + worktree + Herdr pane), and the
`/basecamp:start-workstream` skill hands off to an execution session that attaches
itself and self-reports into a shared Logseq dossier. Design record and build
plan: `docs/design/copilot-claude-port.md`.

### Per-repo `environments` (worktree setup)

`src/basecamp/workspace/` owns the per-repo worktree-setup `environments` config
(a `setup` command keyed by `<org>/<name>` in `~/.pi/basecamp/config.json`), read
by the config layer and managed via `basecamp config env …`. basecamp ships no
default; a repo with no environment is a clean no-op.

## Development

- **Python**: 3.12+, managed with `uv`. There is no Node/TypeScript toolchain.
- **Install (dev)**: `uv run install.py` (or `make install`) does the full bootstrap — `uv tool install` the `basecamp` tool, register the plugin with Claude Code, install the home doctrine block, and seed config. Re-run just the wiring with `basecamp install`.
- **Iterate on the CLI**: `uv run install.py` installs a **non-editable** snapshot on PATH, so for live iteration against your working tree run the CLI via `uv run basecamp <cmd>` (the `uv sync` editable dev venv) rather than re-installing after each change.
- **Lint**: `uv run ruff check .` / `uv run ruff format --check .`; `make lint` runs both.
- **Fix**: `make fix` runs `ruff check --fix` + `ruff format`.
- **Ruff config** (root `pyproject.toml`): `line-length = 120`; the `select` set includes `ARG` (unused arguments fail lint). Ruff-only — no mypy/pyright.

### File Length Limits

A soft **500-line** cap on most source files, tests included, with per-type
exceptions (shell ~400; SQL and HTML ~800). basecamp is Python, so 500 applies
here. It is not CI-enforced (the TypeScript lint gate that carried it is gone);
it lives in the engineering doctrine and the non-blocking warn hook (see above),
which resolves the cap per type via `_LANGUAGE_CAPS`. Treat it as a module-design
forcing function — split along responsibility seams, never by compressing style
or with `-part2` continuation files.

### Testing

- **Run all**: `make test` runs `uv run pytest`.
- **Layout**: `testpaths` is root `tests/`, one subdir per domain (`tests/claude/`, `tests/hub/claude/`, `tests/mcp/`, `tests/hooks/`, `tests/core/`, `tests/workspace/`) beside the CLI-shell tests (`tests/test_cli_*.py`). Imports resolve via the editable install (`uv sync`); no `pythonpath` stitching.
- **Hooks stay hermetic**: hook tests stub the transcript-ingest RPC so no real socket is opened.

## Pull Requests

Open every PR **as a draft** and drive it to done in order — never skip a step or
open one ready for review:

1. **Open in draft.** No PR starts ready for review.
2. **Get CI green.** Poll the PR's checks (`.github/workflows/ci.yml` — ruff lint, ruff format, pytest) and fix whatever fails; do not proceed while CI is red.
3. **Mark ready once CI is green.** Flipping the PR out of draft is also what triggers `.github/workflows/claude-review.yml` (it skips drafts), so the reviewer only ever sees a green, ready PR.
4. **Clear the review.** Poll for the Claude review, fix every issue it raises, and reply to and/or resolve every review comment before treating the PR as done.
