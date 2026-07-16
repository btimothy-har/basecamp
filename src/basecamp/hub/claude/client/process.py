"""Daemon process discovery and termination for the ensure-daemon client.

Ports the connector's ``process.ts``: resolve the daemon pid from the pidfile
(validated against the process command line so we never signal an unrelated
pid), then SIGTERM → wait → SIGKILL, and clear the socket + pidfile. Used only
when a live daemon reports an incompatible protocol.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

#: Total time to wait for a signalled daemon to exit before escalating.
DEFAULT_STOP_TIMEOUT_S = 2.0
#: Poll interval while waiting for exit.
DEFAULT_POLL_S = 0.1


def pid_alive(pid: int) -> bool:
    """Whether ``pid`` names a live process (``kill(pid, 0)`` semantics)."""

    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_pidfile(pidfile: Path) -> int | None:
    """Read an integer pid from ``pidfile``; ``None`` if missing/unparseable."""

    try:
        raw = pidfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _cmdline_is_daemon(pid: int, socket_path: str) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    args = result.stdout.strip()
    return "basecamp" in args and "hub" in args and socket_path in args


def resolve_daemon_pid(pidfile: Path, socket_path: str) -> int | None:
    """Resolve the daemon's pid, or ``None`` unless it is live and ours."""

    pid = read_pidfile(pidfile)
    if pid is None or not pid_alive(pid):
        return None
    if not _cmdline_is_daemon(pid, socket_path):
        return None
    return pid


def _wait_for_exit(
    pid: int,
    timeout_s: float,
    poll_s: float,
    sleep: Callable[[float], None],
    now: Callable[[], float],
) -> bool:
    deadline = now() + timeout_s
    while now() <= deadline:
        if not pid_alive(pid):
            return True
        sleep(poll_s)
    return not pid_alive(pid)


def terminate_daemon(
    pidfile: Path,
    socket_path: str,
    *,
    stop_timeout_s: float = DEFAULT_STOP_TIMEOUT_S,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> None:
    """Stop the daemon (SIGTERM → wait → SIGKILL) and clear its socket + pidfile."""

    pid = resolve_daemon_pid(pidfile, socket_path)
    if pid is not None and pid_alive(pid):
        _signal(pid, signal.SIGTERM)
        if not _wait_for_exit(pid, stop_timeout_s, poll_s, sleep, now):
            _signal(pid, signal.SIGKILL)
            _wait_for_exit(pid, stop_timeout_s, poll_s, sleep, now)
    _unlink(Path(socket_path))
    _unlink(pidfile)


def _signal(pid: int, sig: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, sig)


def _unlink(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.unlink()
