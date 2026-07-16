"""Session-lifecycle RPCs the Claude Code hooks call.

``register_session`` ensures a daemon is up (spawning one if needed) then POSTs
the register frame. ``end_session`` is deliberately best-effort: it never spawns
a daemon just to mark a session ended — if none is reachable there is nothing to
end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..frames import RegisterFrame, serialize_frame
from .paths import DaemonPaths, daemon_paths
from .spawn import ensure_daemon
from .transport import health_ping, post_json


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
    """Best-effort mark a session ended; ``False`` if no daemon is reachable."""

    resolved = paths or daemon_paths()
    socket = str(resolved.socket)
    if not health_ping(socket).ok:
        return False
    status, body = post_json(socket, f"/sessions/{session_id}/end", {})
    return status == 200 and isinstance(body, dict) and bool(body.get("ended"))
