"""Ensure-daemon client: the lightweight, FastAPI-free side of the hub.

Short-lived callers (the Claude Code session hooks) use this to guarantee a
compatible daemon is running and to register/end sessions over HTTP-over-UDS.
Importing this package pulls only httpx + the pydantic frame contract — never
the daemon's FastAPI/uvicorn app.
"""

from __future__ import annotations

from .errors import DaemonError, DaemonProtocolMismatchError, DaemonUnavailableError
from .identity import build_register_body
from .paths import DaemonPaths, daemon_paths
from .sessions import RegisterOutcome, end_session, ingest_transcript, register_session
from .spawn import ensure_daemon
from .transport import HealthResult, get_json, health_ping, post_json
from .workstreams import (
    WorkstreamCreateOutcome,
    create_workstream,
    get_workstream,
    get_workstream_by_worktree,
    list_workstreams,
    set_workstream_status,
)

__all__ = [
    "DaemonError",
    "DaemonPaths",
    "DaemonProtocolMismatchError",
    "DaemonUnavailableError",
    "HealthResult",
    "RegisterOutcome",
    "WorkstreamCreateOutcome",
    "build_register_body",
    "create_workstream",
    "daemon_paths",
    "end_session",
    "ensure_daemon",
    "get_json",
    "get_workstream",
    "get_workstream_by_worktree",
    "health_ping",
    "ingest_transcript",
    "list_workstreams",
    "post_json",
    "register_session",
    "set_workstream_status",
]
