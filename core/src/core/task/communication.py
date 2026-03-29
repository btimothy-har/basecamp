"""Inter-agent communication via Claude CLI session management."""

from __future__ import annotations

import os
import subprocess

from core.constants import CLAUDE_COMMAND
from core.exceptions import NotAWorkerError, ProjectNotSetError, TaskCommunicationError, TaskNotFoundError
from core.task.index import TaskIndex


def _resolve_target_session(name: str) -> str:
    """Resolve a target name to a session ID.

    If name is "parent", resolves to the parent_session_id of the current
    worker's task entry (requires BASECAMP_TASK_NAME).

    Otherwise, looks up the task by name in the index and returns its session_id.
    """
    project = os.environ.get("BASECAMP_PROJECT")
    if not project:
        raise ProjectNotSetError

    index = TaskIndex(project)

    if name == "parent":
        task_name = os.environ.get("BASECAMP_TASK_NAME")
        if not task_name:
            raise NotAWorkerError
        entry = index.get(task_name)
        if entry is None:
            raise TaskNotFoundError(task_name, project)
        return entry.parent_session_id

    entry = index.get(name)
    if entry is None:
        raise TaskNotFoundError(name, project)
    return entry.session_id


def send_message(*, name: str, message: str, direct: bool = False) -> str:
    """Send a message to a target session and return the response.

    Args:
        name: Target task name or "parent" keyword.
        message: The message/question to send.
        direct: If True, inject into target's thread (resume mode).
                If False (default), fork target's context (non-disruptive).

    Returns:
        The text response from the target session.
    """
    session_id = _resolve_target_session(name)

    if direct:
        cmd = [CLAUDE_COMMAND, "-p", "--resume", session_id, message]
    else:
        cmd = [CLAUDE_COMMAND, "-p", "-r", session_id, "--fork-session", "--no-session-persistence", message]

    result = subprocess.run(
        cmd,
        check=False, capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise TaskCommunicationError(result.returncode, result.stderr.strip())

    return result.stdout.strip()
