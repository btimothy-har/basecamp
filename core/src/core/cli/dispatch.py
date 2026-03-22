"""Dispatch implementation for basecamp CLI — launches parallel Claude workers in terminal panes."""

import os
import re
import shlex
import stat
import time
import uuid
from pathlib import Path

from core.constants import (
    CLAUDE_COMMAND,
    SCRIPT_DIR,
)
from core.exceptions import (
    InvalidTaskNameError,
    NoMultiplexerError,
    SessionIdNotSetError,
    TasksDirNotSetError,
)
from core.terminal import resolve_dispatch_backend
from core.ui import console

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _build_launcher_script(
    *,
    model: str,
    system_prompt_file: str | None,
    settings_file: str | None,
    prompt_file: str | None,
    plugin_dirs: list[str],
) -> str:
    """Build a bash launcher script that reads prompt files and execs claude.

    Using a script avoids shell quoting issues when passing commands through
    terminal multiplexers. Files are read via $(cat ...) within the script's
    own shell context.
    """
    parts = [CLAUDE_COMMAND, "--model", shlex.quote(model)]

    if system_prompt_file:
        parts.extend(["--system-prompt", f'"$(cat {shlex.quote(system_prompt_file)})"'])

    if settings_file:
        parts.extend(["--setting-sources", "project,local", "--settings", shlex.quote(settings_file)])

    for plugin_dir in plugin_dirs:
        parts.extend(["--plugin-dir", shlex.quote(plugin_dir)])

    if prompt_file:
        # End-of-options separator ensures the prompt isn't misinterpreted as a flag
        parts.append("--")
        parts.append(f'"$(cat {shlex.quote(prompt_file)})"')

    return "#!/bin/bash\nexec " + " ".join(parts) + "\n"


def execute_dispatch(
    *,
    name: str | None = None,
    model: str = "sonnet",
) -> None:
    """Dispatch a task to a parallel Claude worker in a new terminal pane.

    Must be run from within a Claude session inside a terminal multiplexer
    (Kitty with remote control, or tmux).

    Raises:
        NoMultiplexerError: If not running inside a terminal multiplexer.
        SessionIdNotSetError: If CLAUDE_SESSION_ID is not set.
        TasksDirNotSetError: If BASECAMP_TASKS_DIR is not set.
        PaneLaunchError: If spawning the terminal pane fails.
    """
    backend = resolve_dispatch_backend()
    if backend is None:
        raise NoMultiplexerError

    if not os.environ.get("CLAUDE_SESSION_ID"):
        raise SessionIdNotSetError

    tasks_dir = os.environ.get("BASECAMP_TASKS_DIR")
    if not tasks_dir:
        raise TasksDirNotSetError

    # Auto-generate name if not provided
    if not name:
        name = f"worker-{uuid.uuid4().hex[:8]}"

    if not _SAFE_NAME_RE.match(name):
        raise InvalidTaskNameError(name)

    # Construct task directory
    task_dir = Path(tasks_dir) / name
    task_dir.mkdir(parents=True, exist_ok=True)

    # Remove stale session_id from a previous dispatch with the same name
    stale_session_id = task_dir / "session_id"
    stale_session_id.unlink(missing_ok=True)

    # Prompt is optional — bare worker if absent
    prompt_file = task_dir / "prompt.md"
    has_prompt = prompt_file.exists()

    # Read persisted paths written by execute_launch() (injected via settings.env)
    system_prompt_file: str | None = None
    system_prompt_env = os.environ.get("BASECAMP_SYSTEM_PROMPT")
    if system_prompt_env and Path(system_prompt_env).exists():
        system_prompt_file = system_prompt_env

    settings_env = os.environ.get("BASECAMP_SETTINGS_FILE")
    settings_file = settings_env if settings_env and Path(settings_env).exists() else None

    # Collect plugin directories — workers load companion only
    plugin_dirs: list[str] = []
    companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
    if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        plugin_dirs.append(str(companion_plugin_dir))

    # Write launcher script — avoids complex shell quoting in terminal commands
    launcher = task_dir / "launch.sh"
    launcher.write_text(
        _build_launcher_script(
            model=model,
            system_prompt_file=system_prompt_file,
            settings_file=settings_file,
            prompt_file=str(prompt_file) if has_prompt else None,
            plugin_dirs=plugin_dirs,
        )
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)

    # Only BASECAMP_TASK_DIR needs multiplexer forwarding — everything else
    # is in the cached settings file which the worker loads via --settings.
    pane_env = {"BASECAMP_TASK_DIR": str(task_dir)}
    backend.spawn_pane(
        launcher,
        env=pane_env,
        cwd=Path.cwd(),
        title=name,
    )

    # Wait for worker to write its session_id (written by SessionStart hook)
    session_id_file = task_dir / "session_id"
    worker_session_id = None
    for _ in range(30):  # up to 15s
        if session_id_file.exists():
            worker_session_id = session_id_file.read_text().strip()
            if worker_session_id:
                break
        time.sleep(0.5)

    console.print(f"[bold green]Dispatched[/bold green] task [cyan]{name}[/cyan]")
    console.print(f"  [dim]Task dir:[/dim] {task_dir}")
    if worker_session_id:
        console.print(f"  [dim]Session:[/dim] {worker_session_id}")
    else:
        console.print(f"  [dim]Session:[/dim] (timed out — check {session_id_file})")
