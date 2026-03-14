"""Dispatch implementation for basecamp CLI — launches parallel Claude workers in tmux panes."""

import os
import shlex
import subprocess
import time

from core.config import Config, resolve_project, validate_dirs
from core.constants import (
    CLAUDE_COMMAND,
    OBSERVER_CONFIG,
    SCRIPT_DIR,
    TASKS_DIR,
)
from core.exceptions import DispatchError, NotInTmuxError, TaskPromptNotFoundError
from core.git import get_repo_name, is_git_repo
from core.prompts import system as prompts
from core.ui import console
from core.utils import is_observer_configured


def execute_dispatch(
    project_name: str,
    config: Config,
    *,
    name: str,
    model: str = "sonnet",
) -> None:
    """Dispatch a task to a parallel Claude worker in a new tmux pane.

    The caller (main Claude session) is expected to have already created the task
    directory and written prompt.md before calling this function.

    Args:
        project_name: The project to dispatch against (for directory/plugin resolution).
        config: The loaded configuration.
        name: Task name — used as directory name and tmux pane title.

    Raises:
        NotInTmuxError: If not running inside a tmux session.
        DispatchError: If CLAUDE_SESSION_ID is not set or tmux command fails.
        TaskPromptNotFoundError: If prompt.md does not exist in the task directory.
        ProjectNotFoundError: If the project is not in the config.
        DirectoryNotFoundError: If project directories don't exist.
    """
    if not os.environ.get("TMUX"):
        raise NotInTmuxError

    session_id = os.environ.get("CLAUDE_SESSION_ID")
    if not session_id:
        raise DispatchError("CLAUDE_SESSION_ID is not set — dispatch must be run from within a Claude session")

    # Construct and validate task directory
    task_dir = TASKS_DIR / session_id / name
    prompt_file = task_dir / "prompt.md"

    if not prompt_file.exists():
        raise TaskPromptNotFoundError(task_dir)

    # Resolve project directory
    project = resolve_project(project_name, config)
    resolved_dirs = validate_dirs(project.dirs)
    primary_dir = resolved_dirs[0]

    # Resolve repo name for BASECAMP_REPO env var
    is_repo = is_git_repo(primary_dir)
    repo_name = get_repo_name(primary_dir) if is_repo else primary_dir.name

    # Assemble the same system prompt as launch.py so workers share behavior
    scratch_name = repo_name or primary_dir.name
    prompt_content, _ = prompts.assemble(
        project, primary_dir, [], is_repo=is_repo, scratch_name=scratch_name
    )

    # Write system prompt to task dir for shell-safe passing via tmux
    if prompt_content:
        system_prompt_file = task_dir / "system_prompt.md"
        system_prompt_file.write_text(prompt_content)

    # Build Claude command — the "$(cat ...)" token is pre-quoted for shell eval:
    # outer double quotes preserve whitespace/newlines in the expanded content,
    # and $() opens a new quoting context so shlex.quote's single quotes work inside it.
    claude_parts: list[str] = [
        CLAUDE_COMMAND,
        "--model", model,
    ]
    if prompt_content:
        claude_parts.extend([
            "--system-prompt", f'"$(cat {shlex.quote(str(system_prompt_file))})"',
        ])
    claude_parts.append(f'"$(cat {shlex.quote(str(prompt_file))})"')

    # Workers load only companion + observer plugins (not marketplace) to stay
    # lightweight and task-focused.
    companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
    if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        claude_parts.extend(["--plugin-dir", str(companion_plugin_dir)])

    observer_plugin_dir = SCRIPT_DIR / "plugins" / "observer"
    if is_observer_configured(OBSERVER_CONFIG) and (observer_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        claude_parts.extend(["--plugin-dir", str(observer_plugin_dir)])

    # Join with spaces (not shlex.join) so $(cat ...) is evaluated by the shell
    shell_cmd = " ".join(claude_parts)

    # Launch in a new tmux pane
    tmux_cmd = [
        "tmux", "split-window", "-v",
        "-e", f"BASECAMP_TASK_DIR={task_dir}",
        "-e", f"BASECAMP_REPO={repo_name}",
        "-c", str(primary_dir),
        shell_cmd,
    ]

    try:
        subprocess.run(tmux_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise DispatchError(f"tmux split-window failed: {e.stderr}") from e

    # Set pane title for identification
    try:
        subprocess.run(
            ["tmux", "select-pane", "-t", "{last}", "-T", name],
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
