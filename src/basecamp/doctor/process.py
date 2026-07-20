"""Read-only daemon liveness probes for doctor safety gates."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Any

from basecamp.core.files import atomic_write_json


class DaemonState(StrEnum):
    """Whether it is safe for an external process to migrate the daemon DB."""

    LIVE = "live"
    DOWN = "down"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class DaemonStatus:
    state: DaemonState
    protocol: int | None = None
    detail: str | None = None


class UnixHTTPConnection(HTTPConnection):
    """Minimal HTTP client over a Unix domain socket."""

    def __init__(self, socket_path: Path, *, timeout: float) -> None:
        super().__init__("localhost", 80, timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        try:
            connection.connect(str(self._socket_path))
        except OSError:
            connection.close()
            raise
        self.sock = connection


class DaemonSpawnLock:
    """Cross-language exclusive-create lock used by the hub spawner."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._payload: dict[str, int] = {}
        self._last_refresh = 0.0

    def __enter__(self) -> DaemonSpawnLock:
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            self._payload = self._new_payload()
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(self._payload, file)
                file.flush()
                os.fsync(file.fileno())
        except (OSError, TypeError, ValueError):
            self._path.unlink(missing_ok=True)
            raise
        self._last_refresh = time.monotonic()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        try:
            current = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if current == self._payload:
            self._path.unlink(missing_ok=True)

    def refresh(self, *, force: bool = False) -> None:
        """Keep the spawner's 30-second stale timer from reclaiming this lock."""
        now = time.monotonic()
        if not force and now - self._last_refresh < 5:
            return
        try:
            current = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            msg = "Hub spawn lock changed during database backup."
            raise FileExistsError(msg) from exc
        if current != self._payload:
            msg = "Hub spawn lock ownership changed during database backup."
            raise FileExistsError(msg)
        self._payload = self._new_payload()
        atomic_write_json(self._path, self._payload, mode=0o600, dir_mode=0o700)
        self._last_refresh = now

    def run_while_refreshing(self, operation: Callable[[], object], *, interval: float = 5.0) -> None:
        """Run a blocking migration while keeping the cross-process lock fresh."""
        stopped = threading.Event()
        refresh_errors: list[OSError] = []

        def heartbeat() -> None:
            while not stopped.wait(interval):
                try:
                    self.refresh(force=True)
                except OSError as exc:
                    refresh_errors.append(exc)
                    return

        thread = threading.Thread(target=heartbeat, name="basecamp-doctor-lock", daemon=True)
        thread.start()
        try:
            operation()
        finally:
            stopped.set()
            thread.join()
        if refresh_errors:
            raise refresh_errors[0]

    def _new_payload(self) -> dict[str, int]:
        return {"pid": os.getpid(), "ts": int(time.time() * 1000)}


def inspect_daemon(
    socket_path: Path,
    pid_path: Path,
    spawn_lock_path: Path,
    *,
    timeout: float = 0.4,
    ignore_spawn_lock: bool = False,
) -> DaemonStatus:
    """Probe health and process ownership without spawning or signalling."""
    health = _health(socket_path, timeout=timeout)
    if health is not None:
        return DaemonStatus(DaemonState.LIVE, protocol=health)

    pid = _read_pid(pid_path)
    if pid is not None and _pid_alive(pid):
        if _pid_matches_socket(pid, socket_path):
            return DaemonStatus(DaemonState.AMBIGUOUS, detail="daemon process is alive but health check failed")
        return DaemonStatus(DaemonState.AMBIGUOUS, detail="pid file names an unrelated live process")

    discovered, scan_failed = _find_daemon_pid(socket_path)
    if discovered is not None:
        return DaemonStatus(DaemonState.AMBIGUOUS, detail="daemon process exists without a healthy socket")
    if scan_failed:
        return DaemonStatus(DaemonState.AMBIGUOUS, detail="could not prove that no daemon process is running")
    if spawn_lock_path.exists() and not ignore_spawn_lock:
        return DaemonStatus(DaemonState.AMBIGUOUS, detail="daemon spawn lock exists")
    if socket_path.exists():
        return DaemonStatus(DaemonState.AMBIGUOUS, detail="daemon socket exists but is not healthy")
    return DaemonStatus(DaemonState.DOWN)


def _health(socket_path: Path, *, timeout: float) -> int | None:
    if not socket_path.exists():
        return None
    connection = UnixHTTPConnection(socket_path, timeout=timeout)
    try:
        connection.request("GET", "/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload: Any = json.loads(response.read().decode("utf-8"))
    except (OSError, HTTPException, UnicodeDecodeError, json.JSONDecodeError):
        return None
    finally:
        try:
            connection.close()
        except OSError:
            pass
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        return None
    protocol = payload.get("protocol")
    return protocol if isinstance(protocol, int) and not isinstance(protocol, bool) else None


def _read_pid(path: Path) -> int | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not re.fullmatch(r"\d+", value):
        return None
    pid = int(value)
    return pid if pid > 1 else None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_matches_socket(pid: int, socket_path: Path) -> bool:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return _is_daemon_command(result.stdout, socket_path)


def _find_daemon_pid(socket_path: Path) -> tuple[int | None, bool]:
    try:
        result = subprocess.run(
            ["ps", "-A", "-o", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None, True
    if result.returncode != 0:
        return None, True
    for line in result.stdout.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if match is None:
            continue
        pid = int(match.group(1))
        if pid != os.getpid() and _is_daemon_command(match.group(2), socket_path):
            return pid, False
    return None, False


def _is_daemon_command(command: str, socket_path: Path) -> bool:
    has_command = re.search(r"(?:^|\s)(?:\S*/)?basecamp\s+(?:swarm\s+daemon|hub)(?:\s|$)", command) is not None
    socket = str(socket_path)
    return has_command and (f"--uds {socket}" in command or f"--uds={socket}" in command)
