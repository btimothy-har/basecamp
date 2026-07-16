"""Ensure-daemon client: the lightweight, FastAPI-free side of the hub.

Short-lived callers (the Claude Code session hooks) use this to guarantee a
compatible daemon is running and to register/end sessions over HTTP-over-UDS.
Importing this package pulls only httpx + the pydantic frame contract — never
the daemon's FastAPI/uvicorn app.
"""

from __future__ import annotations

from .errors import DaemonError, DaemonProtocolMismatchError, DaemonUnavailableError
from .identity import build_register_frame
from .paths import DaemonPaths, daemon_paths
from .sessions import RegisterOutcome, end_session, register_session
from .spawn import ensure_daemon
from .transport import HealthResult, health_ping, post_json

__all__ = [
    "DaemonError",
    "DaemonPaths",
    "DaemonProtocolMismatchError",
    "DaemonUnavailableError",
    "HealthResult",
    "RegisterOutcome",
    "build_register_frame",
    "daemon_paths",
    "end_session",
    "ensure_daemon",
    "health_ping",
    "post_json",
    "register_session",
]
