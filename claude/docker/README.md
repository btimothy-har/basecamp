# basecamp × Claude Code — validation sandbox

An interactive container for exercising the basecamp Claude Code plugin end to
end, **isolated from your host**. It builds the `basecamp` Python tool from the
working tree, installs the `claude` CLI, loads this repo's plugin (`claude/`),
and drops you into a shell where a normal `claude` session drives the full
lifecycle:

```
SessionStart hook ─▶ basecamp hub daemon (spawned on demand)
                         │
Claude session ──▶ transcript JSONL ──▶ SessionEnd/PreCompact/SubagentStop hooks
                         │
                         ▼
              ~/.pi/basecamp/claude/daemon.db   (sessions · episodes · transcript_nodes)
```

## Why a container

The hub daemon and Claude Code both key their storage off `$HOME`:

| Data | Path | 
| --- | --- |
| Hub daemon DB | `$HOME/.pi/basecamp/claude/daemon.db` |
| Session transcripts | `$HOME/.claude/projects/<slug>/<session_id>.jsonl` |

Inside the container `$HOME` is `/home/node`, so **nothing is mounted from and
nothing writes back to your host** `~/.pi` or `~/.claude`. You get a clean DB to
validate against without polluting your real basecamp data. The container is run
`--rm`, so each run starts empty.

## Prerequisites

- **podman** (default) or **docker**. On macOS with podman, make sure the
  machine is up: `podman machine start`.
- **Anthropic auth exported in your shell.** `run.sh` forwards the full
  auth/routing triplet at runtime (never baked into the image):
  `ANTHROPIC_API_KEY`, and — for a gateway/proxy setup — `ANTHROPIC_BASE_URL`
  and `ANTHROPIC_CUSTOM_HEADERS`. (`CLAUDE_CODE_*` vars from an outer Claude Code
  session are intentionally not forwarded.)

## Use

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # your host key (+ BASE_URL/CUSTOM_HEADERS if on a gateway)
./claude/docker/run.sh                   # build + interactive shell (podman)
```

Docker instead of podman, or a custom tag:

```bash
ENGINE=docker ./claude/docker/run.sh
IMAGE=my-tag  ./claude/docker/run.sh
```

Or drive the engine yourself (build context must be the repo root):

```bash
podman build -f claude/docker/Dockerfile -t basecamp-claude-sandbox .
podman run --rm -it \
  -e ANTHROPIC_API_KEY -e ANTHROPIC_BASE_URL -e ANTHROPIC_CUSTOM_HEADERS \
  basecamp-claude-sandbox
```

## Inside the container

You land in `~/workspace` (a throwaway git repo). Then:

```bash
claude                 # start a session — the plugin auto-loads
                       # (alias for: claude --plugin-dir "$BASECAMP_PLUGIN_DIR")
# ...interact, then exit the session...

bc-inspect             # dump sessions / episodes / transcript_nodes from the DB
```

A successful validation looks like: after one session, `bc-inspect` shows a row
in `sessions`, at least one `episodes` row (its `ended_at` populated once the
session ends), and `transcript_nodes` for the session id.

Other things to poke at:

```bash
cat ~/.pi/basecamp/claude/hooks.log      # fail-open hook errors, if any
ls  ~/.claude/projects/*/                 # the raw transcript JSONL
sqlite3 ~/.pi/basecamp/claude/daemon.db '.tables'
```

## How it's wired

- **Base:** `node:22-bookworm-slim` (for the `claude` CLI) + `uv` (for Python /
  the basecamp tool). `git` and `sqlite3` are installed for project resolution
  and DB inspection.
- **basecamp:** `uv tool install` from the copied `src/`, exposing `basecamp`,
  `basecamp-mcp`, and `basecamp-hook` on the `node` user's PATH — exactly what the
  plugin's `bin/` shims resolve.
- **Plugin loading:** an interactive-shell alias adds `--plugin-dir
  "$BASECAMP_PLUGIN_DIR"`, so the plugin's hooks, stdio MCP server, and skills
  activate for every `claude` invocation. (Persistent alternative: an
  `enabledPlugins` entry in `~/.claude/settings.json`.)
- **Permissions:** `~/.claude/settings.json` sets `permissions.defaultMode:
  "bypassPermissions"` so the throwaway sandbox never prompts. This is why the
  container runs as the non-root `node` user — Claude Code refuses that mode as
  root.

## Notes / caveats

- **First interactive run** may show a one-time Claude Code theme / folder-trust
  prompt; accept it and continue.
- **Rebuild after source changes** — the image copies `src/` and `claude/` at
  build time, so re-run `run.sh` (or `podman build`) to pick up edits.
- **Pin the CLI** with `--build-arg CLAUDE_CODE_VERSION=x.y.z` if you need a
  specific `claude` version; it defaults to `latest`.
- **This is a validation tool, not a shipped artifact** — it is not installed by
  `basecamp install` and has no bearing on how the plugin is delivered.
