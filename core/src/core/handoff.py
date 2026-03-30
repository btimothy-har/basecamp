"""Handoff: summarize current session and spawn a new one with compact context."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import uuid
from importlib.resources import files
from pathlib import Path

from core.constants import CLAUDE_COMMAND, SCRATCH_BASE, SCRIPT_DIR
from core.exceptions import (
    NoMultiplexerError,
    ProjectNotSetError,
    SessionIdNotSetError,
    TaskCommunicationError,
)
from core.settings import resolve_model
from core.terminal import resolve_dispatch_backend

HANDOFF_PROMPT = (files("core.prompts._system_prompts") / "handoff.md").read_text()


def _require_env(var: str, error: type[Exception]) -> str:
    value = os.environ.get(var)
    if not value:
        raise error()
    return value


def _resolve_launch_config() -> tuple[str | None, str | None, list[str]]:
    """Resolve system prompt file, settings file, and plugin dirs from env."""
    system_prompt_file: str | None = None
    system_prompt_env = os.environ.get("BASECAMP_SYSTEM_PROMPT")
    if system_prompt_env and Path(system_prompt_env).exists():
        system_prompt_file = system_prompt_env

    settings_env = os.environ.get("BASECAMP_SETTINGS_FILE")
    settings_file = settings_env if settings_env and Path(settings_env).exists() else None

    plugin_dirs: list[str] = []
    companion_plugin_dir = SCRIPT_DIR / "plugins" / "companion"
    if (companion_plugin_dir / ".claude-plugin" / "plugin.json").exists():
        plugin_dirs.append(str(companion_plugin_dir))

    return system_prompt_file, settings_file, plugin_dirs


def _summarize_session(session_id: str) -> str:
    """Fork the current session and generate a compact summary."""
    cmd = [
        CLAUDE_COMMAND,
        "-p",
        "-r",
        session_id,
        "--fork-session",
        "--no-session-persistence",
        "--",
        HANDOFF_PROMPT,
    ]

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        raise TaskCommunicationError(result.returncode, result.stderr.strip())

    summary = result.stdout.strip()
    if not summary:
        msg = "Summarization returned empty output"
        raise TaskCommunicationError(1, msg)

    return summary


def _build_launcher_script(
    *,
    model: str,
    session_id: str,
    system_prompt_file: str | None,
    settings_file: str | None,
    prompt_file: str,
    plugin_dirs: list[str],
) -> str:
    """Build a bash launcher script for the handoff session."""
    parts = [CLAUDE_COMMAND, "--model", shlex.quote(model), "--session-id", shlex.quote(session_id)]

    if system_prompt_file:
        parts.extend(["--system-prompt", f'"$(cat {shlex.quote(system_prompt_file)})"'])

    if settings_file:
        parts.extend(["--setting-sources", "project,local", "--settings", shlex.quote(settings_file)])

    for plugin_dir in plugin_dirs:
        parts.extend(["--plugin-dir", shlex.quote(plugin_dir)])

    parts.append("--")
    parts.append(f'"$(cat {shlex.quote(prompt_file)})"')

    return "#!/bin/bash\nexec " + " ".join(parts) + "\n"


def execute_handoff(*, model: str = "sonnet") -> str:
    """Summarize the current session and spawn a new one in a new pane.

    Returns:
        The name/label of the handoff (for display purposes).
    """
    session_id = _require_env("CLAUDE_SESSION_ID", SessionIdNotSetError)
    project = _require_env("BASECAMP_PROJECT", ProjectNotSetError)

    backend = resolve_dispatch_backend()
    if backend is None:
        raise NoMultiplexerError

    # Summarize current session via fork
    summary = _summarize_session(session_id)

    # Write handoff artifacts
    handoff_id = uuid.uuid4().hex[:8]
    handoff_name = f"handoff-{handoff_id}"
    handoff_dir = SCRATCH_BASE / "handoffs" / project / handoff_name
    handoff_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    # Wrap summary as continuation context
    wrapped = (
        "This session is a continuation from a prior session. "
        "Here is a summary of what happened before:\n\n"
        "<handoff-context>\n"
        f"{summary}\n"
        "</handoff-context>\n\n"
        "Wait for the user's next instruction before proceeding."
    )

    prompt_file = handoff_dir / "prompt.md"
    prompt_file.write_text(wrapped)
    prompt_file.chmod(0o600)

    # Build launcher
    resolved_model = resolve_model(model)
    new_session_id = str(uuid.uuid4())
    system_prompt_file, settings_file, plugin_dirs = _resolve_launch_config()

    launcher = handoff_dir / "launch.sh"
    launcher.write_text(
        _build_launcher_script(
            model=resolved_model,
            session_id=new_session_id,
            system_prompt_file=system_prompt_file,
            settings_file=settings_file,
            prompt_file=str(prompt_file),
            plugin_dirs=plugin_dirs,
        )
    )
    launcher.chmod(stat.S_IRWXU)

    # Spawn new pane
    pane_env = {k: v for k, v in os.environ.items() if k.startswith("BASECAMP_")}
    backend.spawn_pane(
        launcher,
        env=pane_env,
        cwd=Path.cwd(),
        title=handoff_name,
    )

    return handoff_name
