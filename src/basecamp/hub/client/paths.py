"""Daemon runtime paths bundled for the ensure-daemon client.

A frozen :class:`DaemonPaths` bundle over the lazy, ``home``-parameterized
helpers in :mod:`basecamp.core.paths`, so the client and tests resolve socket /
lock / pidfile / db from one place (single-sourced with the daemon's own
``store.text.default_db_path``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basecamp.core.paths import (
    daemon_db_path,
    daemon_pidfile_path,
    daemon_socket_path,
    daemon_spawn_lock_path,
    swarm_runtime_dir,
)


@dataclass(frozen=True)
class DaemonPaths:
    """Absolute paths for the hub daemon's runtime files."""

    runtime_dir: Path
    socket: Path
    spawn_lock: Path
    pidfile: Path
    db: Path


def daemon_paths(home: Path | None = None) -> DaemonPaths:
    """Bundle the daemon's runtime paths, rooted at ``home`` (default ``~``)."""

    return DaemonPaths(
        runtime_dir=swarm_runtime_dir(home),
        socket=daemon_socket_path(home),
        spawn_lock=daemon_spawn_lock_path(home),
        pidfile=daemon_pidfile_path(home),
        db=daemon_db_path(home),
    )
