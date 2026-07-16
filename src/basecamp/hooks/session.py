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


def _str_field(payload: Mapping[str, Any], key: str) -> str | None:
    """Return a non-empty string payload field, else ``None``.

    Normalizes an empty string to ``None`` (mirroring the identity builder's
    ``_clean``) so an absent ``source``/``reason``/``cwd`` is stored as NULL rather
    than "" if Claude Code ever sends the key with an empty value.
    """

    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def handle_session_start(payload: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> None:
    """Register a top-level session and open a fresh episode for it."""

    if payload.get("agent_type") == "subagent":
        return
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    cwd = _str_field(payload, "cwd")
    transcript = _str_field(payload, "transcript_path")
    source = _str_field(payload, "source")
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
    reason = _str_field(payload, "reason")
    end_session(session_id, reason=reason)
