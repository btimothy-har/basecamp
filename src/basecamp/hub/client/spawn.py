"""Ensure a compatible hub daemon is running (spawn one if needed).

A faithful port of the retired connector's ``spawn.ts``. The whole operation
shares one 5 s budget:

1. Probe ``/health``; if a matching-protocol daemon answers, return at once.
2. Otherwise acquire an exclusive-create spawn lock (serializing concurrent
   starts), re-probe under the lock, terminate a live-but-incompatible daemon,
   spawn ``basecamp hub`` detached, then poll until healthy — holding the lock
   until the poll finishes so contenders wait rather than double-spawn.
3. On ``EEXIST`` (a contender holds the lock): reclaim it if stale (dead pid or
   >30 s old), else adopt the daemon it brings up, else back off and retry.

Injectable clock/spawn/health/terminate hooks keep it deterministically testable.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ..frames import PROTOCOL_VERSION
from .errors import DaemonProtocolMismatchError, DaemonUnavailableError
from .paths import DaemonPaths
from .process import pid_alive, terminate_daemon
from .transport import DEFAULT_HEALTH_TIMEOUT_S, HealthResult, health_ping

STARTUP_TIMEOUT_S = 5.0
LOCK_RETRY_S = 0.1
LOCK_STALE_AFTER_S = 30.0

HealthPing = Callable[[str, float], HealthResult]
SpawnDaemon = Callable[[DaemonPaths], None]
TerminateDaemon = Callable[[Path, str], None]


def default_daemon_command(paths: DaemonPaths) -> list[str]:
    """The argv used to launch the daemon (``basecamp`` on PATH, else ``-m``)."""

    basecamp_bin = shutil.which("basecamp")
    base = [basecamp_bin] if basecamp_bin else [sys.executable, "-m", "basecamp.cli"]
    return [
        *base,
        "hub",
        "--uds",
        str(paths.socket),
        "--pidfile",
        str(paths.pidfile),
        "--db",
        str(paths.db),
    ]


def default_spawn_daemon(paths: DaemonPaths) -> None:
    """Launch the daemon detached, fully backgrounded (own session, no stdio)."""

    subprocess.Popen(  # noqa: S603 - argv is built from trusted, fixed parts
        default_daemon_command(paths),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def ensure_daemon(
    paths: DaemonPaths,
    *,
    protocol_version: int = PROTOCOL_VERSION,
    ping: HealthPing = health_ping,
    spawn: SpawnDaemon = default_spawn_daemon,
    terminate: TerminateDaemon = terminate_daemon,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    wall_clock: Callable[[], float] = time.time,
) -> str:
    """Return the socket path of a live, protocol-matching daemon, spawning if needed."""

    socket = str(paths.socket)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o700)

    first = ping(socket, DEFAULT_HEALTH_TIMEOUT_S)
    if first.ok and first.protocol == protocol_version:
        return socket

    deadline = monotonic() + STARTUP_TIMEOUT_S
    lock_fd: int | None = None
    try:
        while monotonic() <= deadline:
            try:
                lock_fd = _acquire_lock(paths.spawn_lock, wall_clock)
            except FileExistsError:
                if _handle_contended_lock(paths, socket, protocol_version, ping, sleep, wall_clock):
                    return socket
                continue

            locked = ping(socket, DEFAULT_HEALTH_TIMEOUT_S)
            if locked.ok:
                if locked.protocol == protocol_version:
                    return socket
                terminate(paths.pidfile, socket)
            spawn(paths)
            break

        return _await_healthy(socket, deadline, protocol_version, ping, sleep, monotonic)
    finally:
        _release_lock(lock_fd, paths.spawn_lock)


def _handle_contended_lock(
    paths: DaemonPaths,
    socket: str,
    protocol_version: int,
    ping: HealthPing,
    sleep: Callable[[float], None],
    wall_clock: Callable[[], float],
) -> bool:
    """Handle an ``EEXIST`` spawn lock. Return True iff a matching daemon is up."""

    if _is_lock_stale(paths.spawn_lock, wall_clock, LOCK_STALE_AFTER_S):
        _unlink(paths.spawn_lock)
        return False
    contender = ping(socket, DEFAULT_HEALTH_TIMEOUT_S)
    if contender.ok and contender.protocol == protocol_version:
        return True
    sleep(LOCK_RETRY_S)
    return False


def _await_healthy(
    socket: str,
    deadline: float,
    protocol_version: int,
    ping: HealthPing,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> str:
    while monotonic() <= deadline:
        result = ping(socket, DEFAULT_HEALTH_TIMEOUT_S)
        if result.ok:
            if result.protocol != protocol_version:
                msg = (
                    f"basecamp hub protocol mismatch at {socket}: daemon={result.protocol}, client={protocol_version}."
                )
                raise DaemonProtocolMismatchError(msg)
            return socket
        sleep(LOCK_RETRY_S)
    msg = f"Timed out waiting for basecamp hub at {socket}."
    raise DaemonUnavailableError(msg)


def _acquire_lock(lock_path: Path, wall_clock: Callable[[], float]) -> int:
    """Exclusively create the spawn lock; raises ``FileExistsError`` if held."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    payload = json.dumps({"pid": os.getpid(), "ts": int(wall_clock() * 1000)})
    os.write(fd, payload.encode("utf-8"))
    return fd


def _release_lock(lock_fd: int | None, lock_path: Path) -> None:
    if lock_fd is None:
        return
    try:
        os.close(lock_fd)
    except OSError:
        pass
    _unlink(lock_path)


def _is_lock_stale(lock_path: Path, wall_clock: Callable[[], float], stale_after_s: float) -> bool:
    try:
        raw = lock_path.read_text(encoding="utf-8")
    except OSError:
        return True
    try:
        data = json.loads(raw)
    except ValueError:
        return True
    if not isinstance(data, dict):
        return True
    pid = data.get("pid")
    ts = data.get("ts")
    if not isinstance(pid, int) or isinstance(pid, bool) or not isinstance(ts, (int, float)):
        return True
    if wall_clock() * 1000 - ts > stale_after_s * 1000:
        return True
    return not pid_alive(pid)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
