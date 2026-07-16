"""Daemon runtime paths bundled for the ensure-daemon client.

A frozen :class:`DaemonPaths` bundle over the lazy, ``home``-parameterized
helpers in :mod:`basecamp.hub.claude.paths`, so the client and tests resolve
socket / lock / pidfile / db from one place — single-sourced with the daemon's
own runtime paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..paths import (
    claude_pidfile_path,
    claude_runtime_dir,
    claude_sessions_db_path,
    claude_socket_path,
    claude_spawn_lock_path,
)


@dataclass(frozen=True)
class DaemonPaths:
    """Absolute paths for the Claude hub daemon's runtime files."""

    runtime_dir: Path
    socket: Path
    spawn_lock: Path
    pidfile: Path
    db: Path


def daemon_paths(home: Path | None = None) -> DaemonPaths:
    """Bundle the Claude daemon's runtime paths, rooted at ``home`` (default ``~``)."""

    return DaemonPaths(
        runtime_dir=claude_runtime_dir(home),
        socket=claude_socket_path(home),
        spawn_lock=claude_spawn_lock_path(home),
        pidfile=claude_pidfile_path(home),
        db=claude_sessions_db_path(home),
    )
