"""Inter-agent communication: ask (fork) and send (inbox)."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from core.constants import CLAUDE_COMMAND, INBOX_BASE
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


def ask_task(*, name: str, message: str) -> str:
    """Fork a target session's context and return a response.

    Non-disruptive — the target session is unmodified. Uses claude CLI
    with --fork-session --no-session-persistence.

    Args:
        name: Target task name or "parent" keyword.
        message: The question to ask.

    Returns:
        The text response grounded in the target's conversation context.
    """
    session_id = _resolve_target_session(name)
    cmd = [CLAUDE_COMMAND, "-p", "-r", session_id, "--fork-session", "--no-session-persistence", "--", message]

    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise TaskCommunicationError(result.returncode, result.stderr.strip())

    return result.stdout.strip()


def send_to_task(*, name: str, message: str, immediate: bool = False) -> Path:
    """Deliver a message to a target session's inbox.

    Fire-and-forget — writes a file to the target's inbox directory.
    Delivery happens via hook on the target session:
    - Normal (.msg): delivered at next Stop event (turn boundary)
    - Immediate (.immediate): delivered at next PostToolUse event

    Args:
        name: Target task name or "parent" keyword.
        message: The message to deliver.
        immediate: If True, use .immediate extension for urgent delivery.

    Returns:
        Path to the written message file.
    """
    session_id = _resolve_target_session(name)
    inbox_dir = INBOX_BASE / session_id
    inbox_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    ext = "immediate" if immediate else "msg"
    filename = f"{time.time_ns()}.{ext}"
    msg_path = inbox_dir / filename

    msg_path.write_text(message)
    msg_path.chmod(0o600)

    return msg_path


def check_inbox(*, peek: bool = False) -> list[str] | int:
    """Read messages from the current session's inbox.

    Args:
        peek: If True, return message count without consuming.

    Returns:
        List of message strings (oldest first) when consuming,
        or int count when peeking.
    """
    inbox_dir = os.environ.get("BASECAMP_INBOX_DIR")
    if not inbox_dir:
        return 0 if peek else []

    inbox_path = Path(inbox_dir)
    if not inbox_path.is_dir():
        return 0 if peek else []

    files = sorted(inbox_path.glob("*.msg")) + sorted(inbox_path.glob("*.immediate"))

    if peek:
        return len(files)

    messages = []
    for f in files:
        content = _consume_file(f)
        if content is not None:
            messages.append(content)

    return messages


def _consume_file(path: Path) -> str | None:
    """Read and delete a message file, returning None if already consumed."""
    try:
        content = path.read_text()
        path.unlink()
    except FileNotFoundError:
        return None
    return content
