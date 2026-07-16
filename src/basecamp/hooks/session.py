"""Session lifecycle hook handlers (register on start, end on stop).

Both handlers key off the hook stdin JSON that Claude Code delivers
(``session_id``, ``cwd``, ``transcript_path``, and — on SessionStart —
``agent_type``). Transient Task-tool subagents are skipped: the hub tracks
top-level sessions, while within-session fan-out is Claude Code's own concern.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from basecamp.hub.client import build_register_frame, end_session, register_session


def handle_session_start(payload: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> None:
    """Register a fresh top-level session with the daemon."""

    if payload.get("agent_type") == "subagent":
        return
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    transcript = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else None
    frame = build_register_frame(
        session_id=session_id,
        cwd=cwd or os.getcwd(),
        transcript_path=transcript,
        env=env,
    )
    register_session(frame)


def handle_session_end(payload: Mapping[str, Any]) -> None:
    """Mark a session ended (best-effort; no-op if the daemon is down)."""

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    end_session(session_id)
