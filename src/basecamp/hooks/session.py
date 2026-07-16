"""Session lifecycle hook handlers (register on start, end on stop).

Both handlers key off the hook stdin JSON that Claude Code delivers
(``session_id``, ``cwd``, ``transcript_path``, and — on SessionStart —
``agent_type``/``source``; on SessionEnd, ``reason``). Transient Task-tool
subagents are skipped: the hub tracks top-level sessions, while within-session
fan-out is Claude Code's own concern.

Liveness is per *episode*, not per session: SessionStart opens an episode
(stamped with its ``source``) and SessionEnd closes it (stamped with its
``reason``). Because a resume or ``/clear`` fires a SessionEnd *and* a matching
SessionStart, both are handled uniformly — the closing/opening pair brackets the
engagement without any special-casing, and the durable session row is never ended.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from basecamp.hub.claude.client import build_register_body, end_session, register_session


def handle_session_start(payload: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> None:
    """Register a top-level session and open a fresh episode for it."""

    if payload.get("agent_type") == "subagent":
        return
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None
    transcript = payload.get("transcript_path") if isinstance(payload.get("transcript_path"), str) else None
    source = payload.get("source") if isinstance(payload.get("source"), str) else None
    body = build_register_body(
        session_id=session_id,
        cwd=cwd or os.getcwd(),
        transcript_path=transcript,
        source=source,
        env=env,
    )
    register_session(body)


def handle_session_end(payload: Mapping[str, Any]) -> None:
    """Close the session's open episode (best-effort; no-op if the daemon is down).

    Every SessionEnd closes the current episode, stamped with its ``reason`` — a
    ``/clear`` or resume is no longer special-cased, because the paired SessionStart
    opens the next episode. The durable ``sessions`` row is never marked ended.
    """

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    reason = payload.get("reason") if isinstance(payload.get("reason"), str) else None
    end_session(session_id, reason=reason)
