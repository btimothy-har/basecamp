"""Cross-client singleton startup for the hub daemon."""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path
from typing import Any

from basecamp.core.exceptions import LauncherError
from basecamp.core.paths import DAEMON_DB, DAEMON_PID, DAEMON_SOCK, DAEMON_SPAWN_LOCK, SWARM_DIR

from .dashboard.uds import UnixSocketHTTPConnection
from .frames import PROTOCOL_VERSION

HEALTH_TIMEOUT_SECONDS = 0.4
STARTUP_TIMEOUT_SECONDS = 5.0
LOCK_STALE_AFTER_MS = 30_000
LOCK_RETRY_SECONDS = 0.1
DAEMON_STOP_TIMEOUT_SECONDS = 2.0


class HubEnsureError(LauncherError):
    """Hub could not be made ready for a client command."""

    @classmethod
    def timeout(cls, socket_path: Path) -> HubEnsureError:
        return cls(f"Timed out waiting for basecamp hub at {socket_path}.")

    @classmethod
    def protocol_mismatch(cls, socket_path: Path, protocol: int) -> HubEnsureError:
        return cls(f"basecamp hub protocol mismatch at {socket_path}: daemon={protocol}, client={PROTOCOL_VERSION}.")

    @classmethod
    def spawn_failed(cls) -> HubEnsureError:
        return cls("Could not start the basecamp hub process.")

    @classmethod
    def restart_failed(cls) -> HubEnsureError:
        return cls("Could not restart the incompatible basecamp hub process.")

    @classmethod
    def runtime_setup_failed(cls, runtime_dir: Path) -> HubEnsureError:
        return cls(f"Could not prepare the basecamp hub runtime directory at {runtime_dir}.")

    @classmethod
    def spawn_lock_failed(cls, lock_path: Path) -> HubEnsureError:
        return cls(f"Could not acquire the basecamp hub spawn lock at {lock_path}.")


@dataclass(frozen=True)
class HubPaths:
    runtime_dir: Path
    socket_path: Path
    spawn_lock_path: Path
    pid_path: Path
    db_path: Path


@dataclass(frozen=True)
class HubHealth:
    ok: bool
    protocol: int | None = None


HealthPing = Callable[[Path, float], HubHealth]
SpawnHub = Callable[[HubPaths], None]
TerminateHub = Callable[[HubPaths], None]


@dataclass(frozen=True)
class EnsureHubDeps:
    health_ping: HealthPing
    spawn_hub: SpawnHub
    terminate_hub: TerminateHub
    pid_exists: Callable[[int], bool]
    wall_clock_ms: Callable[[], int]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]


def default_hub_paths() -> HubPaths:
    return HubPaths(
        runtime_dir=SWARM_DIR,
        socket_path=DAEMON_SOCK,
        spawn_lock_path=DAEMON_SPAWN_LOCK,
        pid_path=DAEMON_PID,
        db_path=DAEMON_DB,
    )


def default_ensure_deps() -> EnsureHubDeps:
    return EnsureHubDeps(
        health_ping=_health_ping,
        spawn_hub=_spawn_hub,
        terminate_hub=_terminate_hub,
        pid_exists=_pid_exists,
        wall_clock_ms=lambda: time.time_ns() // 1_000_000,
        monotonic=time.monotonic,
        sleep=time.sleep,
    )


def ensure_hub(
    *,
    paths: HubPaths | None = None,
    deps: EnsureHubDeps | None = None,
    startup_timeout: float = STARTUP_TIMEOUT_SECONDS,
    health_timeout: float = HEALTH_TIMEOUT_SECONDS,
    lock_stale_after_ms: int = LOCK_STALE_AFTER_MS,
    lock_retry: float = LOCK_RETRY_SECONDS,
) -> Path:
    """Start or reuse one protocol-compatible hub and return its UDS path."""

    runtime = paths or default_hub_paths()
    operations = deps or default_ensure_deps()
    try:
        runtime.runtime_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        os.chmod(runtime.runtime_dir, 0o700)
    except OSError as error:
        raise HubEnsureError.runtime_setup_failed(runtime.runtime_dir) from error

    first_health = operations.health_ping(runtime.socket_path, health_timeout)
    if _health_matches(first_health):
        return runtime.socket_path

    lock_deadline = operations.monotonic() + startup_timeout
    readiness_deadline = lock_deadline
    lock_fd: int | None = None
    lock_identity: tuple[int, int] | None = None
    last_health = first_health
    try:
        while operations.monotonic() <= lock_deadline:
            try:
                lock_fd, lock_identity = _acquire_spawn_lock(
                    runtime.spawn_lock_path,
                    operations.wall_clock_ms(),
                )
            except FileExistsError:
                if _spawn_lock_is_stale(
                    runtime.spawn_lock_path,
                    operations.wall_clock_ms(),
                    lock_stale_after_ms,
                    operations.pid_exists,
                ):
                    try:
                        _unlink(runtime.spawn_lock_path)
                    except OSError as error:
                        raise HubEnsureError.spawn_lock_failed(runtime.spawn_lock_path) from error
                    continue
                last_health = operations.health_ping(runtime.socket_path, health_timeout)
                if _health_matches(last_health):
                    return runtime.socket_path
                operations.sleep(lock_retry)
                continue
            except OSError as error:
                raise HubEnsureError.spawn_lock_failed(runtime.spawn_lock_path) from error

            locked_health = operations.health_ping(runtime.socket_path, health_timeout)
            if _health_matches(locked_health):
                return runtime.socket_path
            if locked_health.ok:
                try:
                    operations.terminate_hub(runtime)
                except OSError as error:
                    raise HubEnsureError.restart_failed() from error
            try:
                operations.spawn_hub(runtime)
            except OSError as error:
                raise HubEnsureError.spawn_failed() from error
            # Contenders share the lock budget; only this caller's spawn earns a full readiness window.
            readiness_deadline = operations.monotonic() + startup_timeout
            break

        while operations.monotonic() <= readiness_deadline:
            last_health = operations.health_ping(runtime.socket_path, health_timeout)
            if last_health.ok:
                break
            operations.sleep(lock_retry)

        if not last_health.ok:
            raise HubEnsureError.timeout(runtime.socket_path)
        if last_health.protocol != PROTOCOL_VERSION:
            raise HubEnsureError.protocol_mismatch(runtime.socket_path, last_health.protocol or -1)
        return runtime.socket_path
    finally:
        if lock_fd is not None and lock_identity is not None:
            _release_spawn_lock(lock_fd, runtime.spawn_lock_path, lock_identity)


def _health_matches(health: HubHealth) -> bool:
    return health.ok and health.protocol == PROTOCOL_VERSION


def _acquire_spawn_lock(lock_path: Path, now_ms: int) -> tuple[int, tuple[int, int]]:
    # Stage the payload in a private sibling and hardlink it into place so a
    # contender can never observe a created-but-not-yet-written lock; an empty
    # lock reads as corrupt, gets reclaimed as stale, and lets two ensures spawn.
    payload = json.dumps({"pid": os.getpid(), "ts": now_ms}, separators=(",", ":")).encode()
    staging_path = lock_path.with_name(f"{lock_path.name}.{os.getpid()}.{secrets.token_hex(8)}")
    fd = os.open(staging_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, payload)
        os.link(staging_path, lock_path)
        stat = os.fstat(fd)
    except BaseException:
        os.close(fd)
        _unlink_quietly(staging_path)
        raise
    _unlink_quietly(staging_path)
    return fd, (stat.st_dev, stat.st_ino)


def _release_spawn_lock(fd: int, lock_path: Path, identity: tuple[int, int]) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        stat = lock_path.stat()
    except OSError:
        return
    if (stat.st_dev, stat.st_ino) == identity:
        _unlink(lock_path)


def _spawn_lock_is_stale(
    lock_path: Path,
    now_ms: int,
    stale_after_ms: int,
    pid_exists: Callable[[int], bool],
) -> bool:
    try:
        value: Any = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    if not isinstance(value, dict):
        return True
    pid = value.get("pid")
    timestamp = value.get("ts")
    if isinstance(pid, bool) or not isinstance(pid, int):
        return True
    if isinstance(timestamp, bool) or not isinstance(timestamp, int | float):
        return True
    return now_ms - timestamp > stale_after_ms or not pid_exists(pid)


def _health_ping(socket_path: Path, timeout: float) -> HubHealth:
    connection = UnixSocketHTTPConnection(str(socket_path), timeout=timeout)
    try:
        connection.request("GET", "/health", headers={"Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(64 * 1024)
        if response.status != 200:
            return HubHealth(ok=False)
        value: Any = json.loads(body.decode("utf-8"))
        protocol = value.get("protocol") if isinstance(value, dict) else None
        if (
            isinstance(value, dict)
            and value.get("status") == "ok"
            and isinstance(protocol, int)
            and not isinstance(protocol, bool)
        ):
            return HubHealth(ok=True, protocol=protocol)
        return HubHealth(ok=False)
    except (OSError, HTTPException, json.JSONDecodeError, UnicodeDecodeError):
        return HubHealth(ok=False)
    finally:
        try:
            connection.close()
        except OSError:
            pass


def _spawn_hub(paths: HubPaths) -> None:
    subprocess.Popen(
        [
            "basecamp",
            "hub",
            "--uds",
            str(paths.socket_path),
            "--pidfile",
            str(paths.pid_path),
            "--db",
            str(paths.db_path),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def _pid_exists(pid: int) -> bool:
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _is_daemon_command(args: str, socket_path: Path) -> bool:
    daemon_command = re.search(r"(?:^|\s)(?:\S*/)?basecamp\s+(?:swarm\s+daemon|hub)(?:\s|$)", args)
    socket_arg = f"--uds {socket_path}" in args or f"--uds={socket_path}" in args
    return daemon_command is not None and socket_arg


def _ps(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["ps", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout if result.returncode == 0 else ""


def _pid_command_matches(pid: int, socket_path: Path) -> bool:
    return any(_is_daemon_command(line, socket_path) for line in _ps(["-p", str(pid), "-o", "args="]).splitlines())


def _read_pid(pid_path: Path) -> int | None:
    try:
        value = pid_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value.isdecimal():
        return None
    pid = int(value)
    return pid if pid > 0 else None


def _find_daemon_pid(paths: HubPaths) -> int | None:
    recorded = _read_pid(paths.pid_path)
    if recorded is not None and recorded != os.getpid():
        if _pid_command_matches(recorded, paths.socket_path):
            return recorded

    for line in _ps(["-A", "-o", "pid=,args="]).splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) != 2 or not parts[0].isdecimal():
            continue
        pid = int(parts[0])
        if pid != os.getpid() and _is_daemon_command(parts[1], paths.socket_path):
            return pid
    return None


def _terminate_hub(paths: HubPaths) -> None:
    pid = _find_daemon_pid(paths)
    if pid is not None and _pid_exists(pid):
        _signal(pid, signal.SIGTERM)
        if not _wait_for_exit(pid):
            _signal(pid, signal.SIGKILL)
            _wait_for_exit(pid)
    _unlink(paths.socket_path)
    _unlink(paths.pid_path)


def _signal(pid: int, process_signal: signal.Signals) -> None:
    try:
        os.kill(pid, process_signal)
    except ProcessLookupError:
        pass


def _wait_for_exit(pid: int) -> bool:
    deadline = time.monotonic() + DAEMON_STOP_TIMEOUT_SECONDS
    while time.monotonic() <= deadline:
        if not _pid_exists(pid):
            return True
        time.sleep(LOCK_RETRY_SECONDS)
    return not _pid_exists(pid)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass
