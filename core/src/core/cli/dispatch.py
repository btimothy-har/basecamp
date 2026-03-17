"""Dispatch implementation for basecamp CLI — launches parallel Claude workers in tmux panes."""

import os
import shlex
import stat
import subprocess
import time
import uuid
from pathlib import Path

from core.constants import (
    CLAUDE_COMMAND,
    OBSERVER_CONFIG,
    SCRIPT_DIR,
    USER_ASSEMBLED_PROMPTS_DIR,
)
from core.exceptions import (
    NotInTmuxError,
    SessionIdNotSetError,
    TasksDirNotSetError,
    TmuxLaunchError,
)
from core.ui import console
from core.utils import is_observer_configured


def _build_launcher_script(
    *,
    model: str,
    system_prompt_file: str | None,
    prompt_file: str | None,
    plugin_dirs: list[str],
) -> str:
    """Build a bash launcher script that reads prompt files and execs claude.

    Using a script avoids shell quoting issues when passing commands through tmux.
    Files are read via $(cat ...) within the script's own shell context.
    """
    parts = [CLAUDE_COMMAND, "--model", shlex.quote(model)]

    if system_prompt_file:
        parts.extend(["--system-prompt", f'"$(cat {shlex.quote(system_prompt_file)})"'])

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
    """Dispatch a task to a parallel Claude worker in a new tmux pane.

    Must be run from within a Claude session (tmux + CLAUDE_SESSION_ID).
    If a task name is provided and prompt.md exists in the task directory,
    the worker receives it as the initial message. Otherwise starts a bare session.

    Raises:
        NotInTmuxError: If not running inside a tmux session.
        SessionIdNotSetError: If CLAUDE_SESSION_ID is not set.
        TasksDirNotSetError: If BASECAMP_TASKS_DIR is not set.
        TmuxLaunchError: If the tmux split-window command fails.
    """
    if not os.environ.get("TMUX"):
        raise NotInTmuxError

    if not os.environ.get("CLAUDE_SESSION_ID"):
        raise SessionIdNotSetError

    tasks_dir = os.environ.get("BASECAMP_TASKS_DIR")
    if not tasks_dir:
        raise TasksDirNotSetError

    # Auto-generate name if not provided
    if not name:
        name = f"worker-{uuid.uuid4().hex[:8]}"

    # Construct task directory
    task_dir = Path(tasks_dir) / name
    task_dir.mkdir(parents=True, exist_ok=True)

    # Prompt is optional — bare worker if absent
    prompt_file = task_dir / "prompt.md"
    has_prompt = prompt_file.exists()

    # Read persisted system prompt from ~/.basecamp/prompts/assembled/{project}.md
    project_name = os.environ.get("BASECAMP_PROJECT")
    system_prompt_file: Path | None = None
    if project_name:
        candidate = USER_ASSEMBLED_PROMPTS_DIR / f"{project_name}.md"
        if candidate.exists():
            system_prompt_file = candidate

    # Collect plugin directories — workers load companion + observer only
    plugin_dirs: list[str] = []
    companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
    if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        plugin_dirs.append(str(companion_plugin_dir))

    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        plugin_dirs.append(str(observer_plugin_dir))

    # Write launcher script — avoids complex shell quoting in the tmux command
    launcher = task_dir / "launch.sh"
    launcher.write_text(
        _build_launcher_script(
            model=model,
            system_prompt_file=str(system_prompt_file) if system_prompt_file else None,
            prompt_file=str(prompt_file) if has_prompt else None,
            plugin_dirs=plugin_dirs,
        )
    )
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)

    # Read env vars to forward to worker pane
    repo_name = os.environ.get("BASECAMP_REPO", "")

    # Launch in a new tmux pane — use -P -F to capture the new pane ID
    tmux_cmd = [
        "tmux",
        "split-window",
        "-v",
        "-P",
        "-F",
        "#{pane_id}",
        "-e",
        f"BASECAMP_TASK_DIR={task_dir}",
        "-e",
        f"BASECAMP_REPO={repo_name}",
        "-c",
        str(Path.cwd()),
        str(launcher),
    ]

    try:
        result = subprocess.run(tmux_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise TmuxLaunchError(e.stderr) from e

    # Set pane title using the captured pane ID
    pane_id = result.stdout.strip()
    if pane_id:
        try:
            subprocess.run(
                ["tmux", "select-pane", "-t", pane_id, "-T", name],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            pass  # Non-critical — pane still works without a title

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
