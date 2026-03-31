"""Worker lifecycle operations: create, dispatch, close, list."""

from __future__ import annotations

import os
import re
import shlex
import stat
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from core.constants import CLAUDE_COMMAND, INBOX_BASE, SCRIPT_DIR, WORKERS_BASE
from core.exceptions import (
    InvalidWorkerNameError,
    NoMultiplexerError,
    ProjectNotSetError,
    SessionIdNotSetError,
    WorkerError,
    WorkerNotFoundError,
)
from core.settings import resolve_model
from core.terminal import resolve_dispatch_backend
from core.worker.index import WorkerIndex
from core.worker.models import WorkerEntry, WorkerStatus

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class LaunchConfig(NamedTuple):
    system_prompt_file: str | None
    settings_file: str | None
    plugin_dirs: list[str]


def _require_project() -> str:
    """Read BASECAMP_PROJECT from environment or raise."""
    project = os.environ.get("BASECAMP_PROJECT")
    if not project:
        raise ProjectNotSetError
    if not _SAFE_NAME_RE.match(project):
        msg = f"BASECAMP_PROJECT contains unsafe characters: {project!r}"
        raise WorkerError(msg)
    return project


def _require_session_id() -> str:
    """Read CLAUDE_SESSION_ID from environment or raise."""
    session_id = os.environ.get("CLAUDE_SESSION_ID")
    if not session_id:
        raise SessionIdNotSetError
    return session_id


def _validate_name(name: str) -> None:
    if not _SAFE_NAME_RE.match(name):
        raise InvalidWorkerNameError(name)


def _build_resume_script(
    *,
    session_id: str,
    settings_file: str | None,
    plugin_dirs: list[str],
) -> str:
    """Build a bash launcher script that resumes an existing Claude session."""
    parts = [CLAUDE_COMMAND, "--resume", shlex.quote(session_id)]

    if settings_file:
        parts.extend(["--setting-sources", "project,local", "--settings", shlex.quote(settings_file)])

    for plugin_dir in plugin_dirs:
        parts.extend(["--plugin-dir", shlex.quote(plugin_dir)])

    return "#!/bin/bash\nexec " + " ".join(parts) + "\n"


def _build_launcher_script(
    *,
    model: str,
    session_id: str,
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
    parts = [CLAUDE_COMMAND, "--model", shlex.quote(model), "--session-id", shlex.quote(session_id)]

    if system_prompt_file:
        parts.extend(["--system-prompt", f'"$(cat {shlex.quote(system_prompt_file)})"'])

    if settings_file:
        parts.extend(["--setting-sources", "project,local", "--settings", shlex.quote(settings_file)])

    for plugin_dir in plugin_dirs:
        parts.extend(["--plugin-dir", shlex.quote(plugin_dir)])

    if prompt_file:
        parts.append("--")
        parts.append(f'"$(cat {shlex.quote(prompt_file)})"')

    return "#!/bin/bash\nexec " + " ".join(parts) + "\n"


def _resolve_launch_config() -> LaunchConfig:
    """Resolve system prompt, settings file, and plugin dirs for the worker launcher."""
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

    return LaunchConfig(system_prompt_file, settings_file, plugin_dirs)


def create_worker(
    *,
    name: str | None = None,
    prompt: str | None = None,
    model: str = "sonnet",
    dispatch: bool = False,
) -> WorkerEntry:
    """Create a worker with its directory, prompt, and launcher script.

    Args:
        name: Worker name (auto-generated if omitted).
        prompt: Worker prompt content (written to prompt.md).
        model: Model for the worker session.
        dispatch: If True, also spawn a terminal pane immediately.

    Returns:
        The created WorkerEntry.
    """
    project = _require_project()
    session_id = _require_session_id()

    prefix = f"worker-{uuid.uuid4().hex[:6]}"
    if name:
        _validate_name(name)
        name = f"{prefix}-{name}"
    else:
        name = prefix

    index = WorkerIndex(project)

    worker_dir = WORKERS_BASE / project / name
    worker_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    prompt_file = worker_dir / "prompt.md"
    if prompt:
        prompt_file.write_text(prompt)
        prompt_file.chmod(0o600)

    resolved = resolve_model(model)
    worker_session_id = str(uuid.uuid4())

    config = _resolve_launch_config()
    launcher = worker_dir / "launch.sh"
    launcher.write_text(
        _build_launcher_script(
            model=resolved,
            session_id=worker_session_id,
            system_prompt_file=config.system_prompt_file,
            settings_file=config.settings_file,
            prompt_file=str(prompt_file) if prompt else None,
            plugin_dirs=config.plugin_dirs,
        )
    )
    launcher.chmod(stat.S_IRWXU)

    entry = WorkerEntry(
        name=name,
        project=project,
        worker_dir=str(worker_dir),
        session_id=worker_session_id,
        parent_session_id=session_id,
        model=resolved,
    )
    index.add(entry)

    if dispatch:
        _spawn_worker(entry, index)

    return entry


def dispatch_worker(*, name: str) -> tuple[WorkerEntry, bool]:
    """Dispatch a worker by spawning a terminal pane, or resume if already dispatched.

    Returns:
        Tuple of (WorkerEntry, resumed) where resumed is True if an existing
        session was resumed rather than a new one spawned.
    """
    project = _require_project()
    index = WorkerIndex(project)

    entry = index.get(name)
    if entry is None:
        raise WorkerNotFoundError(name, project)

    resumed = _spawn_worker(entry, index)
    return entry, resumed


def _spawn_worker(entry: WorkerEntry, index: WorkerIndex) -> bool:
    """Spawn a terminal pane for a worker and update its status.

    If the worker is already dispatched, the existing session is resumed via
    ``claude --resume`` instead of starting a fresh one.

    Returns:
        True if an existing session was resumed, False if a new session was spawned.
    """
    backend = resolve_dispatch_backend()
    if backend is None:
        raise NoMultiplexerError

    worker_dir = Path(entry.worker_dir)
    launcher = worker_dir / "launch.sh"
    resumed = entry.status == WorkerStatus.DISPATCHED

    if resumed:
        config = _resolve_launch_config()
        launcher.write_text(
            _build_resume_script(
                session_id=entry.session_id,
                settings_file=config.settings_file,
                plugin_dirs=config.plugin_dirs,
            )
        )
        launcher.chmod(stat.S_IRWXU)

    pane_env = {k: v for k, v in os.environ.items() if k.startswith("BASECAMP_")}
    pane_env["BASECAMP_WORKER_DIR"] = str(worker_dir)
    pane_env["BASECAMP_WORKER_NAME"] = entry.name
    pane_env["BASECAMP_INBOX_DIR"] = str(INBOX_BASE / entry.session_id)
    backend.spawn_pane(
        launcher,
        env=pane_env,
        cwd=Path.cwd(),
        title=entry.name,
    )

    if not resumed:
        index.update(entry.name, status=WorkerStatus.DISPATCHED)
        entry.status = WorkerStatus.DISPATCHED  # sync in-memory state

    return resumed


def close_worker() -> None:
    """Mark a worker as closed.

    Called by the SessionEnd hook inside a dispatched worker.
    Reads BASECAMP_PROJECT and BASECAMP_WORKER_NAME from environment.
    No-op if BASECAMP_WORKER_NAME is not set (main session, not a worker).
    """
    name = os.environ.get("BASECAMP_WORKER_NAME")
    if not name:
        return

    project = _require_project()
    index = WorkerIndex(project)

    entry = index.get(name)
    if entry is None or entry.status == WorkerStatus.CLOSED:
        return

    index.update(name, status=WorkerStatus.CLOSED, closed_at=datetime.now(timezone.utc))


def list_workers(*, show_all: bool = False) -> list[WorkerEntry]:
    """List workers for the current project.

    By default, filters to workers created by the current session.
    Use show_all=True to see all workers for the project.
    """
    project = _require_project()
    index = WorkerIndex(project)
    entries = index.read()

    if not show_all:
        current_session = os.environ.get("CLAUDE_SESSION_ID", "")
        entries = [e for e in entries if e.parent_session_id == current_session]

    return entries
