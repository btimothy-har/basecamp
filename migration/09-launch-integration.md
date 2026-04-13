# 09 — Update Core Launch to Use Extension

## Goal

Update `core/src/core/cli/launch.py` to pass the basecamp extension to pi instead of the companion Claude Code plugin. This also means switching from `claude` CLI to `pi` CLI.

## Current State

**File:** `core/src/core/cli/launch.py`

The launch function currently:
1. Builds a `claude` command
2. Adds `--plugin-dir` pointing to the companion plugin
3. Passes `--system-prompt`, `--add-dir`, `--settings` flags
4. Launches via terminal backend

**File:** `core/src/core/constants.py`

```python
CLAUDE_COMMAND = "claude"
```

## Changes Required

### 1. Update `constants.py`

```python
# Replace:
CLAUDE_COMMAND = "claude"

# With:
PI_COMMAND = "pi"
```

Add the extension directory constant:

```python
EXTENSION_DIR = SCRIPT_DIR / "extension"
```

Note: `SCRIPT_DIR` is the install root written by `install.py`. The extension directory will be bundled alongside `core/` and `observer/` at install time. `install.py` may need a small update to copy `extension/` into the install root.

### 2. Update `launch.py`

Replace the companion plugin loading with pi extension loading:

```python
# REMOVE:
companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
    cmd.extend(["--plugin-dir", str(companion_plugin_dir)])

# REPLACE WITH:
from core.constants import EXTENSION_DIR
if (EXTENSION_DIR / "package.json").exists():
    cmd.extend(["-e", str(EXTENSION_DIR)])
```

Replace the CLI command:

```python
# REMOVE:
cmd: list[str] = [CLAUDE_COMMAND]

# REPLACE WITH:
cmd: list[str] = [PI_COMMAND]
```

### 3. Map Claude CLI flags to pi CLI flags

| Claude flag | Pi equivalent | Notes |
|------------|---------------|-------|
| `--system-prompt <text>` | `--system-prompt <text>` | Same flag, pi supports it |
| `--add-dir <path>` | Check pi docs | May not exist in pi — verify |
| `--settings <path>` | May not exist | Pi uses `~/.pi/agent/settings.json` — env vars may need different injection |
| `--setting-sources` | May not exist | Pi-specific settings model |
| `--plugin-dir <path>` | `-e <path>` | Extension path |

### 4. Handle settings / env var injection

The current `build_session_settings()` in `core/src/core/config/claude_settings.py` builds a Claude-format settings.json with:
- `env` block (BASECAMP_* vars, .env vars)
- `permissions.allow` (pre-authorized paths)

Pi's settings model is different. Options:
1. **Set env vars directly** — since pi extensions run in the same process, `process.env` is shared. Basecamp can set `BASECAMP_*` env vars on the terminal session (tmux/Kitty env forwarding already works) instead of injecting them via a settings file.
2. **Use pi's settings.json** — pi has its own `~/.pi/agent/settings.json` format. Check if it supports an `env` block or equivalent.
3. **Hybrid** — env vars via terminal forwarding, pi-specific config via `.pi/settings.json` in the project.

### 5. Handle system prompt

Pi supports `--system-prompt` directly. The current flow writes the prompt to a cache file AND passes it via `--system-prompt`. Keep both — the cache file is needed for dispatch workers.

### 6. Update `install.py`

The install script needs to copy `extension/` into the install root so `EXTENSION_DIR` resolves correctly:

```python
# In install.py, add extension directory to the install copy list
shutil.copytree(repo_root / "extension", install_dir / "extension", dirs_exist_ok=True)
```

### 7. Update tests

Any tests that reference `CLAUDE_COMMAND` or companion plugin paths need updating. Check:
- `core/tests/` for mock command construction
- Test fixtures that reference plugin directories

## Open Questions

- **Does pi support `--add-dir`?** Check `pi --help`. If not, secondary directories may need to be handled differently (possibly via the extension's `session_start` or by setting cwd).
- **Does pi support `--system-prompt`?** Verify the exact flag name.
- **Pi settings format** — Review pi's settings.json schema to determine how to inject env vars and permissions.
- **Is the `--setting-sources` flag needed?** This controls Claude Code's settings merge behavior. Pi likely doesn't have this concept.

## Acceptance Criteria

- [ ] `constants.py` uses `PI_COMMAND` instead of `CLAUDE_COMMAND`
- [ ] `constants.py` defines `EXTENSION_DIR`
- [ ] `launch.py` passes `-e <extension_dir>` instead of `--plugin-dir`
- [ ] `launch.py` builds a `pi` command instead of `claude`
- [ ] `BASECAMP_*` env vars reach the extension (verify via `process.env` in session_start)
- [ ] System prompt passed correctly
- [ ] `install.py` copies `extension/` to install root
- [ ] `basecamp launch <project>` successfully starts a pi session with the extension loaded
- [ ] All skills discoverable via `/skill:` in the launched session
- [ ] Tests updated and passing
