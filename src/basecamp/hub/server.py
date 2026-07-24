"""Daemon server runner."""

from __future__ import annotations

import asyncio
import fcntl
import os
import socket as socket_module
from pathlib import Path

import uvicorn

from basecamp.core.exceptions import LauncherError
from basecamp.core.paths import DAEMON_SERVER_LOCK

from .app import create_app
from .dashboard.access import DashboardAccess
from .dashboard.server import DashboardServer
from .store import Store
from .swarm.process import reconcile_orphaned_runs
from .swarm.sweep import run_periodic_sweep

_SOCKET_MODE = 0o600
_SERVER_LOCK_MODE = 0o600
_DEFAULT_SWEEP_INTERVAL_S = 3600.0


class HubAlreadyRunningError(LauncherError):
    """Another hub process owns this runtime directory."""

    def __init__(self, lock_path: Path) -> None:
        super().__init__(f"A basecamp hub is already running ({lock_path}).")


class UdsServer(uvicorn.Server):
    """uvicorn server that tightens the UDS to owner-only after binding.

    uvicorn binds the socket and chmods it to 0666 inside ``startup()``; doing
    the restriction afterwards is the only reliable point and preserves the
    local-user-only trust boundary (the lifespan hook runs before the bind).

    When *sweep_interval_s* is set, a periodic agent-worktree sweep task is
    started after the socket is bound and cancelled/awaited on shutdown — the
    server holds the server lock for its whole lifetime, so the sweep task's
    lifecycle is bounded by the daemon's own.
    """

    def __init__(self, config: uvicorn.Config, *, sweep_interval_s: float | None = None) -> None:
        super().__init__(config)
        self._sweep_interval_s = sweep_interval_s
        self._sweep_task: asyncio.Task[None] | None = None

    async def startup(self, sockets: list[socket_module.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        uds = self.config.uds
        if uds:
            try:
                os.chmod(uds, _SOCKET_MODE)
            except OSError as exc:
                msg = f"failed to restrict daemon socket {uds} to {oct(_SOCKET_MODE)}"
                raise RuntimeError(msg) from exc
        if self._sweep_interval_s is not None and self._sweep_interval_s > 0:
            self._sweep_task = asyncio.create_task(run_periodic_sweep(self._sweep_interval_s))

    async def shutdown(self, sockets: list[socket_module.socket] | None = None) -> None:
        task = self._sweep_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._sweep_task = None
        await super().shutdown(sockets=sockets)


def create_server(
    uds_path: str,
    store: Store,
    *,
    dashboard_access: DashboardAccess | None = None,
    log_level: str = "info",
    sweep_interval_s: float | None = None,
) -> UdsServer:
    """Build a UDS-bound daemon server for the given store."""

    app = create_app(store, daemon_uds=uds_path, dashboard_access=dashboard_access)
    config = uvicorn.Config(app, uds=uds_path, log_level=log_level)
    return UdsServer(config, sweep_interval_s=sweep_interval_s)


def _resolve_sweep_interval_s() -> float | None:
    """Read the sweep interval from the environment, defaulting to 3600s.

    A non-positive or unparseable value disables the periodic sweep (returns None).
    """
    raw = os.environ.get("BASECAMP_AGENT_SWEEP_INTERVAL_S")
    if raw is None:
        return _DEFAULT_SWEEP_INTERVAL_S
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_SWEEP_INTERVAL_S
    return value if value > 0 else None


def _acquire_server_lock(lock_path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, _SERVER_LOCK_MODE)
    try:
        os.fchmod(fd, _SERVER_LOCK_MODE)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(fd)
        raise HubAlreadyRunningError(lock_path) from error
    except BaseException:
        os.close(fd)
        raise
    return fd


def _release_server_lock(fd: int) -> None:
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _write_pid_file(pid_path: Path, pid: int) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{pid}\n", encoding="utf-8")
    os.chmod(pid_path, 0o600)


def _remove_pid_file(pid_path: Path, pid: int) -> None:
    try:
        recorded_pid = pid_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return

    if recorded_pid != str(pid):
        return

    try:
        pid_path.unlink()
    except FileNotFoundError:
        return


def run_hub(
    uds_path: str,
    db_path: str | None = None,
    pid_path: str | None = None,
) -> None:
    """Run the hub daemon bound to a Unix domain socket."""

    socket_path = Path(uds_path).expanduser()
    socket_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(socket_path.parent, 0o700)
    server_lock = _acquire_server_lock(socket_path.parent / DAEMON_SERVER_LOCK.name)
    daemon_pid = os.getpid()
    daemon_pid_path = Path(pid_path).expanduser() if pid_path is not None else None
    dashboard: DashboardServer | None = None
    try:
        if socket_path.exists():
            socket_path.unlink()
        if daemon_pid_path is not None:
            _write_pid_file(daemon_pid_path, daemon_pid)

        store = Store(db_path=db_path)
        reconcile_orphaned_runs(store)
        sweep_interval_s = _resolve_sweep_interval_s()
        dashboard_access = DashboardAccess()
        dashboard = DashboardServer(access=dashboard_access, uds_path=str(socket_path))
        dashboard.start()
        create_server(
            str(socket_path),
            store,
            dashboard_access=dashboard_access,
            sweep_interval_s=sweep_interval_s,
        ).run()
    finally:
        if dashboard is not None:
            dashboard.stop()
        if daemon_pid_path is not None:
            _remove_pid_file(daemon_pid_path, daemon_pid)
        _release_server_lock(server_lock)
