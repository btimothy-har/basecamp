# basecamp

Project-aware Pi extension for AI coding agents. Configures project context, manages isolated git worktrees, and supports workflow automation.

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp && uv run install.py
basecamp setup
pi
```

## Why basecamp?

When working with AI coding agents across multiple projects, you face friction:

- **Scattered context** — Each project needs different prompts, working styles, and domain knowledge
- **Branch conflicts** — Parallel conversations on the same repo compete for the working directory
- **Repetitive setup** — Re-configuring directories and prompts for each session

basecamp solves this with a Pi extension that:

1. **Replaces the default system prompt** — Full control over behavior, consistency across sessions, tailored to your workflow
2. **Configures project context** — Detects configured projects from the repo you launch Pi in and loads project-specific prompts automatically
3. **Supports isolated worktrees** — Planning starts in the protected repo root; approved implementation work activates a labeled worktree
4. **Manages multi-repo projects** — Groups related repositories under one project definition

## Installation

Requires [uv](https://docs.astral.sh/uv/) and [pi](https://github.com/earendil-works/pi).

```bash
git clone https://github.com/btimothy-har/basecamp.git
cd basecamp
uv run install.py           # interactive (prompts for editable mode)
uv run install.py -e        # editable (recommended for development)
uv run install.py --no-editable
```

This installs the Python tool `basecamp`, prompts for optional Basecamp Pi package groups, and saves installer metadata to `~/.pi/basecamp/config.json`.

Then initialize the environment:

```bash
basecamp setup                     # check prerequisites, create workspace dirs, create default project config
```

If `basecamp` isn't in your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrading

```bash
uv tool upgrade basecamp
```

### Uninstalling

```bash
uv tool uninstall basecamp
```

## Usage

### Launching Sessions

Launch sessions with plain Pi from the repo or subdirectory you want to work in. Basecamp detects the git repository root and loads the matching project when its `repo_root` is configured.

```bash
cd ~/GitHub/web-app
pi                         # Detects project by repo_root

cd ~/GitHub/web-app/src/api
pi                         # Also detects the same project from the git root

pi --style advisor         # Optional working style override
```

If the launch cwd's git root does not match a configured `repo_root`, Basecamp starts an unprojected Pi session.

### Managing Projects

Project configuration is managed through the projects menu:

```bash
basecamp projects
```

Use it to list, add, edit, or remove configured projects.

### Slash Commands (in-session)

| Command | Description |
|---------|-------------|
| `/show-plan` | Show the current plan and task progress |
| `/worktree [label]` | Switch to an existing Git-registered worktree |
| `/create-pr` | Create or update a pull request |
| `/skill:code-review` | Run an independent multi-agent review of the current branch |
| `/title [text]` | Generate a session title from the conversation, or set one manually |
| `/model-aliases` | Manage model aliases (list, add, edit, remove) |

### Browser Automation

Primary sessions can load the `playwright-cli` skill to automate an installed Chrome or Brave browser. Basecamp uses an exact-pinned local CLI through its gated `playwright-cli` command—no global install, browser download, or MCP server is required. Accessibility snapshots and element refs are the default interaction loop; screenshots are written outside the repository and then inspected with Pi's `read` tool.

Playwright starts with a fresh managed persistent profile, and browser artifacts default to the private bounded directory `~/.pi/basecamp/browser/playwright-output`. Set `BASECAMP_BROWSER_PATH` for a custom Chromium executable; explicit `PLAYWRIGHT_MCP_*` environment overrides are also honored. Browser access is not exposed to subagents. Upgrades do not migrate or delete the former `~/.pi/basecamp/browser/profile`.

### Frontend Design

Basecamp ships a model-invocable `frontend-design` skill for code-first interface work—pages, components, dashboards, prototypes, responsive redesigns, and visual polish. It works in an existing project's stack or creates one self-contained HTML file with inline CSS and JavaScript for focused framework-free exploration. Runnable source is the deliverable; screenshots are reference and verification evidence, while image generation is reserved for explicitly requested assets.

In primary sessions, the skill composes with `playwright-cli` for live inspection, responsive screenshots, runtime checks, and optional annotated feedback. Standalone HTML previews use an isolated route-backed origin and require no additional preview server.

### Subagents

Use the `agents` skill for agent selection and async daemon dispatch guidance:

```js
skill({ name: "agents" })
dispatch_agent({ agent: "scout", task: "Investigate the auth module" }) // returns an agent handle
list_agents({ awaitable: true })
wait_for_agent({ handles: "<agent-handle>" })
```

Built-in agents: `scout`, `worker`, `devils-advocate`, `security-specialist`, `testing-specialist`, `docs-specialist`, `code-clarity-specialist`, `conventions-specialist`, `general-reviewer`.

Named read-only agents may fan out for parallel investigation and review. Mutative workers may also run in parallel because each receives its own locked, per-run worktree and branch. Basecamp gives mutating sessions one hidden reminder to commit dirty work, reclaims clean worker worktrees automatically, and preserves live or dirty trees rather than force-removing them.

### Agents dashboard

Open the global, read-only session dashboard from any directory:

```bash
basecamp agents
```

The command starts or reuses the single Basecamp hub, mints a 30-second one-time browser login over the owner-only daemon socket, and opens the dashboard. If the system browser cannot be opened, it prints the short-lived fallback URL instead. Run the command again when browser authentication expires.

The dashboard groups top-level Root, Workstream, and Copilot sessions by repository and worktree. It always includes every connected root, including sessions with no child agents, plus the five newest disconnected roots seen within the last 24 hours. An explicit **Load 5 more sessions** control expands disconnected history up to 50 roots; the selected session stays pinned while eligible. Filters cover repository, worktree, kind, live status, agent status, and agent type. Session pages show bounded goal-cycle/task history and recursive agent topology; public-handle agent pages show ancestry, descendants, current task, recent allowlisted activity, skills, previews, and at most three assistant messages. Polling pauses while the page is hidden and retains the last safe in-memory snapshot during a transient failure or busy refresh.

The browser surface is deliberately narrower than the daemon:

- It binds only `127.0.0.1:47658`; the port is fixed and a collision disables the dashboard without stopping the UDS hub.
- It exposes no dispatch, cancel, messaging, mutation, workstream-management, or daemon WebSocket routes.
- Browser payloads omit private IDs, paths, session files, prompts/specs, environment data, report tokens, raw tool inputs/results, hidden thinking, and full result/error bodies.
- Authentication state and bootstrap nonces exist only in hub memory. The loopback HTTP cookie is host-only, `HttpOnly`, and `SameSite=Strict`; no login secret is written to disk.
- The 24-hour disconnected-session window and 50-root loader ceiling are display rules, not retention policy. Older SQLite rows are left untouched, and live roots remain visible regardless of age.

This is a single-user localhost surface, not a remote dashboard: there is no configurable bind address, TLS layer, CORS, or multi-user authorization.

## Configuration

Projects are defined in `~/.pi/basecamp/workspace/projects.json`:

```json
{
  "version": 1,
  "projects": {
    "web-app": {
      "repo_root": "GitHub/web-app",
      "additional_dirs": [],
      "description": "Main web application",
      "working_style": "engineering"
    },
    "data-pipeline": {
      "repo_root": "GitHub/pipeline",
      "additional_dirs": ["GitHub/pipeline-config"],
      "description": "ETL pipeline and configuration",
      "working_style": "engineering",
      "context": "pipeline"
    }
  }
}
```

Root `~/.pi/basecamp/config.json` holds installer-owned metadata (`install_dir`, `installed_modules`) and per-repo worktree `environments` (see [Worktree environments](#worktree-environments)); it does not contain project definitions.

| Field | Required | Description |
|-------|----------|-------------|
| `repo_root` | Yes | Path relative to `$HOME` for the git repository root used to detect the project |
| `additional_dirs` | No | Extra project directories included in prompt context and allowed file roots |
| `description` | No | Shown in `basecamp projects` listings |
| `working_style` | No | Loads matching working style prompt (see below) |
| `context` | No | Stem only (no `.md`); loads `~/.pi/basecamp/workspace/context/{name}.md` for project context |

Existing local config files with the older project directory schema are migrated to `repo_root` and `additional_dirs` by setup/projects flows.

## Prompt System

basecamp replaces the default system prompt via a `before_agent_start` hook. This gives you:

- **Full control** — Define how the agent approaches work, not defaults
- **Consistency** — Same behavior across sessions; immune to upstream prompt changes
- **Customization** — Prompts designed for your specific workflow

Pi's tool definitions and skill listings are sourced dynamically and included in the assembled prompt.

### Prompt Assembly

The system prompt is assembled from layered sources:

```
mode prompt, plus read-only constraints when applicable
         ↓
working style prompt, or subagent prompt for dispatched agents
         ↓
environment.md (CLI usage, Python/uv)
         ↓
capabilities index (tools, skills, and parent-session agents)
         ↓
project context (configured context plus AGENTS.md/CLAUDE.md)
         ↓
runtime environment (paths, platform, date, git/worktree state)
```

Built-in prompt files can be overridden by creating matching files under `~/.pi/basecamp/workspace/prompts/` (for example, `~/.pi/basecamp/workspace/prompts/environment.md` or `~/.pi/basecamp/workspace/prompts/modes/work.md`).

### Session Modes

The session mode sets the agent's posture and is shown in the footer. Cycle between `analysis`, `explore` (planning), and `work` (the default) with shift+tab. Dispatched subagents are read-only; the primary session is the sole mutator.

`copilot` is a locked, launch-only mode: start it with `pi --copilot`. It is immutable — shift+tab can neither enter nor leave it — and the `plan()` handoff is disabled in it (a copilot session stages execution-ready workstreams with `launch_workstream` instead of implementing in-session). `pi --copilot` takes precedence over `pi --workstream` if both are passed.

### Working Styles

| Style | Description |
|-------|-------------|
| `engineering` | Partner role, collaborative work, code quality focus, frequent check-ins |
| `advisor` | Advisor role, efficient discovery, direct communication, decision support |
| `logseq` | Knowledge graph curation, structured entries, user-driven content approval |

Create custom working styles as `{name}.md` files in `~/.pi/basecamp/workspace/styles/`.

### Project Context

For multi-repo projects, add cross-repo context in `~/.pi/basecamp/workspace/context/`. The `context` field in project config is the file stem only; Basecamp appends `.md` when loading the matching file.

Single-repo projects typically use `AGENTS.md` in the repo itself.

## Git Worktrees

Before a worktree is active, the effective working directory is where you launched Pi; the repository root is the protected checkout boundary for workspace guards. When an implementation plan is approved, Basecamp uses the workspace service to prompt for an execution worktree using existing worktrees plus a suggested label derived from the plan goal.

The workspace service owns the `~/.worktrees/<org>/<name>/<label>/` storage convention, `wt/<label>` default branch names, and `/tmp/pi/<org>/<name>` scratch directories. Git is the source of truth for worktree registration; Basecamp consumes workspace state for project context and exposes `BASECAMP_*` env vars to child processes and integrated services.

- The protected checkout must be on the default branch with a clean working tree before activation
- Implementation edits happen in the active worktree, not the protected checkout
- Relative file-tool paths target the active worktree after activation, preserving the launch subdirectory when applicable
- Mutating `git`/`gh` commands run through the bash reviewer, and edits or git operations are blocked unless the effective cwd is inside the active execution worktree
- `--worktree-dir` is an internal attach-only Pi flag for existing Git-registered worktrees; it does not create worktrees
- Resumed/reloaded/forked sessions restore their last active worktree when still in the same repo
- `/worktree [label]` switches the active worktree during a resumed session
- Session-owned worktrees remain human-managed; outside Pi, use native Git commands (`git worktree list`, `git worktree remove`) to inspect or clean them up
- Additional directories stay on their configured checkouts throughout the session
- Only works with git repositories

### Worktree environments

A fresh worktree contains tracked files only — gitignored artifacts (`.venv`, `node_modules`, `.env`, build output) are absent. To provision newly created worktrees, configure a per-repo **environment**: a setup command keyed by repo name.

```bash
basecamp environments                       # interactive menu (list / add / edit / remove)
basecamp environments list
basecamp environments set <org>/<name> "uv sync && npm ci"
basecamp environments remove <org>/<name>
```

Environments are stored under the `environments` section of `~/.pi/basecamp/config.json`, keyed by the canonical `<org>/<name>` repo identity (derived from the origin remote URL, falling back to the bare git basename) — i.e. `BASECAMP_REPO`:

```json
{ "environments": { "acme/basecamp": { "setup": "uv sync && npm ci" } } }
```

basecamp ships no default — a repo with no environment is a clean no-op. When an approved implementation plan **creates** a new execution worktree, basecamp resolves the current repo's setup command and runs it before handoff:

- Executed as `bash -lc "<command>"` with the working directory set to the new worktree.
- Inherits the `BASECAMP_*` env vars plus `BASECAMP_REPO_ROOT` (the protected checkout path), so the command can copy or symlink artifacts from the source checkout if it chooses. basecamp does not prescribe what the command does.
- **Blocks** activation with a **180-second timeout**; the fresh session starts only once setup finishes.
- **Warn-and-proceed**: a non-zero exit or timeout surfaces a warning and is recorded in the handoff result, but activation and handoff still complete.
- **Creation only**: it does not run when resuming/attaching an existing worktree or switching via `/worktree`.

For anything beyond a one-liner, point the command at a script you maintain outside the repo, e.g. `"bash ~/.pi/basecamp/worktree-setup.sh"`.

## Terminal-Bench Evaluation

Basecamp includes a repository-local [Harbor](https://harborframework.com) adapter for running Pi with Basecamp on Terminal-Bench 2.1. Harbor runs on the host and creates a fresh, disposable Docker container for every task attempt; Pi and Basecamp execute only inside that trial container.

Prerequisites:

- Python 3.12+ and `uv`
- Docker, or a running Podman machine
- A dedicated, scoped model-provider API key
- A committed Basecamp revision; uncommitted and untracked files are deliberately excluded

Install the pinned harness stack:

```bash
uv tool install --force --prerelease explicit \
  --with 'litellm==1.90.2' \
  'harbor==0.20.1.dev202607210139'
```

For Podman on macOS, the launcher puts Basecamp's compatibility wrapper on `PATH` automatically. It uses `DOCKER_COMPOSE_BIN` or an installed `docker-compose` when available; otherwise it downloads Docker Compose v5.3.1 into `~/.cache/basecamp/evals/`, verifies the pinned SHA-256, and points it at the running Podman machine's API socket. `podman-compose` is not compatible with Harbor because it does not accept Compose's `--project-directory` option.

From the Basecamp repository root, export the scoped provider credentials referenced by your Pi configuration, then use the Make targets:

```bash
export OPENAI_API_KEY='<scoped-key>'
export PI_PROXY_API_KEY='<scoped-proxy-key>'

make eval-dry       # print the resolved tasks and Harbor command
make eval-install   # install/config/auth smoke without model completions
make eval           # run the selected tasks (paid model calls)
```

The default `podman-arm64` preset runs the three native-arm64 tasks whose 2 GiB limits fit the local Podman machine:

- `terminal-bench/hf-model-inference`
- `terminal-bench/mteb-retrieve`
- `terminal-bench/pytorch-model-recovery`

Useful overrides:

```bash
# Include the fourth native-arm64 task (8 GiB limit)
make eval EVAL_SELECTION=podman-arm64-all

# Choose arbitrary tasks
make eval EVAL_SELECTION="hf-model-inference pytorch-model-recovery"

# Repeat tasks and control parallelism
make eval EVAL_ATTEMPTS=3 EVAL_CONCURRENCY=2

# Change model/runtime settings
make eval EVAL_MODEL=shopify/fireworks:accounts/fireworks/models/glm-5p2 \
  EVAL_THINKING=high EVAL_PI_VERSION=0.80.7

# Use Docker, omit models.json, or change the result root
make eval EVAL_ENGINE=docker EVAL_EXTRA=--no-models \
  EVAL_JOBS_DIR="$HOME/evals/other-terminal-bench-jobs"
```

`make eval` is the explicit paid-run action. `make eval-dry` permits a dirty worktree because it does not launch Harbor; executable runs require a clean worktree so the printed Git commit identifies the exact Basecamp source. Change the provider key and `EVAL_MODEL` together when using another provider. Harbor passes provider credentials into each trial container; do not use a broad personal or organization key. `make eval-install` requires `pi --list-models` to contain the exact configured provider/model before Harbor removes each trial container.

`pi_models_file` is optional. When present, the adapter snapshots and digest-verifies that `models.json`, copies it to the trial user's Pi config with mode `0600`, and forwards host environment variables referenced by provider `apiKey` or header interpolation. Literal API keys and credential commands are rejected. `auth.json`, `settings.json`, and secret values are never copied into metadata or the Basecamp source archive.

The adapter installs the exact Pi version and a `git archive` of `package.json`, `package-lock.json`, and `pi/` from the clean `HEAD` commit resolved by the launcher. It verifies the archive digest, installs production dependencies from the committed lockfile without lifecycle scripts, and registers Basecamp with Pi. It never mounts host Pi auth, Basecamp configuration, worktrees, or the repository into the trial container.

This is the worker-like `basecamp-pi-single` profile. It retains Basecamp's system prompt, skills, task workflow, project/workspace behavior, engineering tools, bash reviewer, and structured file tools. It disables the Python hub, dispatched subagents, browser, workstreams, code-review UI, and interactive `plan()` flow. The adapter marks the trial with `BASECAMP_EXTERNAL_SANDBOX=1` and supplies both `--unsafe-edit` and `--unsafe-edit-sandboxed`; Basecamp requires all three signals before allowing `edit`/`write` in a headless subagent session. Read-only and ordinary headless or subagent sessions remain protected.

Harbor writes each job and trial beneath `EVAL_JOBS_DIR` (default: `~/evals/basecamp-terminal-bench/jobs`). The useful per-trial files are:

- `result.json` — reward, timing, and exception data
- `agent/pi.txt` — Pi's filtered JSON event stream
- `agent/pi/sessions/` — Pi session data
- `agent/basecamp-eval.json` — Basecamp commit, archive digest, profile, and runtime versions
- `verifier/` — reward and verifier output

Browse completed jobs with:

```bash
harbor view "$HOME/evals/basecamp-terminal-bench/jobs"
```

Docker and Podman-on-macOS through the included wrapper are supported. Most Terminal-Bench 2.1 task images are amd64-only and x64 Node can crash under arm64 emulation, so the Podman presets select the four images that publish native arm64 variants. Runs produce local scores and Pi logs, not ATIF trajectories, so they are not eligible for the Terminal-Bench 2.1 leaderboard. Harbor's usage totals cover the parent Pi process and may not include auxiliary bash-reviewer model calls.

## Package Layout

basecamp is organized by the artifacts it ships:

- `pi/` — the single Pi extension (`pi/extension.ts` + `pi/<domain>/`), registered from the repo root: project context, session UI, worktrees, workflow, git, engineering, browser, agents, code review, and workstream features
- `src/basecamp/` — the single `basecamp` Python distribution (one ordinary src-layout package): setup/config/install CLI plus the `core`, `workspace`, and `hub` (daemon + agents dashboard) subpackages
- `evals/` — non-shipping evaluation integrations; currently the Harbor adapter for isolated Terminal-Bench runs of Pi with Basecamp

## License

Apache 2.0
