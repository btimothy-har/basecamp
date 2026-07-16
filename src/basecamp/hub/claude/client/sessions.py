"""Session-lifecycle RPCs the Claude Code hooks call.

``register_session`` ensures a daemon is up (spawning one if needed) then POSTs
the register frame. ``end_session`` is deliberately best-effort: it never spawns
a daemon just to mark a session ended — if none is reachable there is nothing to
end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ...frames import RegisterFrame, serialize_frame
from .paths import DaemonPaths, daemon_paths
from .spawn import ensure_daemon
from .transport import post_json


@dataclass(frozen=True)
class RegisterOutcome:
    """Result of a register POST."""

    status: int
    body: Any


def register_session(frame: RegisterFrame, *, paths: DaemonPaths | None = None) -> RegisterOutcome:
    """Ensure the daemon is running, then register ``frame``. May raise DaemonError."""

    resolved = paths or daemon_paths()
    socket = ensure_daemon(resolved)
    status, body = post_json(socket, "/sessions", serialize_frame(frame))
    return RegisterOutcome(status=status, body=body)


def end_session(session_id: str, *, paths: DaemonPaths | None = None) -> bool:
    """Best-effort mark a session ended; ``False`` if the daemon is unreachable.

    Never spawns a daemon (nothing to end if none is reachable) and never raises:
    a single POST whose transport failure — no socket, connection refused mid-race
    — resolves to ``False`` instead of two round-trips (health probe + POST).
    """

    resolved = paths or daemon_paths()
    try:
        status, body = post_json(str(resolved.socket), f"/sessions/{session_id}/end", {})
    except (httpx.HTTPError, OSError):
        return False
    return status == 200 and isinstance(body, dict) and bool(body.get("ended"))
