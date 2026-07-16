"""Session-lifecycle RPCs the Claude Code hooks call.

``register_session`` ensures a daemon is up (spawning one if needed) then POSTs
the register body. ``end_session`` and ``ingest_transcript`` are deliberately
best-effort: they never spawn a daemon — if none is reachable there is nothing to
end and nowhere to ingest into — and never raise, resolving a transport failure to
``False`` rather than breaking the (fail-open) hook.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..contract import SessionRegisterBody
from .paths import DaemonPaths, daemon_paths
from .spawn import ensure_daemon
from .transport import post_json


@dataclass(frozen=True)
class RegisterOutcome:
    """Result of a register POST."""

    status: int
    body: Any


def register_session(body: SessionRegisterBody, *, paths: DaemonPaths | None = None) -> RegisterOutcome:
    """Ensure the daemon is running, then register ``body``. May raise DaemonError."""

    resolved = paths or daemon_paths()
    socket = ensure_daemon(resolved)
    status, response = post_json(socket, "/sessions", body.model_dump(mode="json"))
    return RegisterOutcome(status=status, body=response)


def end_session(session_id: str, *, reason: str | None = None, paths: DaemonPaths | None = None) -> bool:
    """Best-effort close a session's open episode; ``False`` if the daemon is unreachable.

    Never spawns a daemon (nothing to end if none is reachable) and never raises:
    a single POST whose transport failure — no socket, connection refused mid-race
    — resolves to ``False`` instead of two round-trips (health probe + POST).
    """

    resolved = paths or daemon_paths()
    try:
        status, body = post_json(str(resolved.socket), f"/sessions/{session_id}/end", {"reason": reason})
    except (httpx.HTTPError, OSError):
        return False
    return status == 200 and isinstance(body, dict) and bool(body.get("ended"))


def ingest_transcript(
    session_id: str,
    *,
    transcript_path: str | None = None,
    reason: str | None = None,
    sweep_sidecars: bool = False,
    agent_transcript_path: str | None = None,
    paths: DaemonPaths | None = None,
) -> bool:
    """Best-effort trigger a transcript ingest; ``False`` if the daemon is unreachable.

    Only posts the trigger — the daemon does the file read. Never spawns (nothing to
    ingest into if none is up) and never raises. The fields select the ingest mode:
    ``transcript_path`` (main; PreCompact supplies it, SessionEnd falls back to the
    stored path), ``sweep_sidecars`` (SessionEnd — walk every sidecar), and
    ``agent_transcript_path`` (SubagentStop — one completed sidecar). Returns whether
    an ingest was scheduled.
    """

    resolved = paths or daemon_paths()
    body = {
        "transcript_path": transcript_path,
        "reason": reason,
        "sweep_sidecars": sweep_sidecars,
        "agent_transcript_path": agent_transcript_path,
    }
    try:
        status, response = post_json(str(resolved.socket), f"/sessions/{session_id}/ingest", body)
    except (httpx.HTTPError, OSError):
        return False
    return status == 200 and isinstance(response, dict) and bool(response.get("scheduled"))
