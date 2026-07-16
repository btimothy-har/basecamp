"""Session lifecycle hook handlers (register on start, end on stop).

Both handlers key off the hook stdin JSON that Claude Code delivers
(``session_id``, ``cwd``, ``transcript_path``, and — on SessionStart —
``agent_type``; on SessionEnd, ``reason``). Transient Task-tool subagents are
skipped: the hub tracks top-level sessions, while within-session fan-out is
Claude Code's own concern.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from basecamp.hub.claude.client import build_register_frame, end_session, register_session, resolve_node_id

# SessionEnd reasons where the *same* session_id keeps running — /clear (context
# reset) and resume (conversation reload), each paired with a SessionStart
# (source=clear/resume) that continues the session. These must NOT mark the row
# ended. Every other reason (logout, prompt_input_exit, bypass_permissions_disabled,
# other) — and an absent/unknown reason — is a genuine termination and defaults to
# ending the row, so a live session never leaks as perpetually-open.
_CONTINUATION_END_REASONS = frozenset({"clear", "resume"})


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


def handle_session_end(payload: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> None:
    """Mark a session ended (best-effort; no-op if the daemon is down).

    Deregisters under the same key SessionStart registered — ``BASECAMP_AGENT_ID``
    when set, else the native session id — so a daemon-spawned worker's row is
    actually closed instead of left dangling. A /clear or resume (the session
    keeps running, only its context resets) is skipped so the still-live row is
    not spuriously marked ended.
    """

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    if payload.get("reason") in _CONTINUATION_END_REASONS:
        return
    end_session(resolve_node_id(session_id, env))
