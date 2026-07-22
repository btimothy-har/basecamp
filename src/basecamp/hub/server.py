"""Daemon server runner."""

from __future__ import annotations

import os
import socket as socket_module
from pathlib import Path

import uvicorn

from .app import create_app
from .dashboard.access import DashboardAccess
from .dashboard.server import DashboardServer
from .store import Store
from .swarm.process import reconcile_orphaned_runs

_SOCKET_MODE = 0o600


class UdsServer(uvicorn.Server):
    """uvicorn server that tightens the UDS to owner-only after binding.

    uvicorn binds the socket and chmods it to 0666 inside ``startup()``; doing
    the restriction afterwards is the only reliable point and preserves the
    local-user-only trust boundary (the lifespan hook runs before the bind).
    """

    async def startup(self, sockets: list[socket_module.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        uds = self.config.uds
        if uds:
            try:
                os.chmod(uds, _SOCKET_MODE)
            except OSError as exc:
                # Fail fast: serving on a socket we couldn't restrict to 0600 would
                # break the local-user-only trust boundary.
                msg = f"failed to restrict daemon socket {uds} to {oct(_SOCKET_MODE)}"
                raise RuntimeError(msg) from exc


def create_server(
    uds_path: str,
    store: Store,
    *,
    dashboard_access: DashboardAccess | None = None,
    log_level: str = "info",
) -> UdsServer:
    """Build a UDS-bound daemon server for the given store."""

    app = create_app(store, daemon_uds=uds_path, dashboard_access=dashboard_access)
    config = uvicorn.Config(app, uds=uds_path, log_level=log_level)
    return UdsServer(config)


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
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    daemon_pid = os.getpid()
    daemon_pid_path = Path(pid_path).expanduser() if pid_path is not None else None
    if daemon_pid_path is not None:
        _write_pid_file(daemon_pid_path, daemon_pid)

    dashboard: DashboardServer | None = None
    try:
        store = Store(db_path=db_path)
        reconcile_orphaned_runs(store)
        dashboard_access = DashboardAccess()
        dashboard = DashboardServer(access=dashboard_access, uds_path=str(socket_path))
        dashboard.start()
        create_server(str(socket_path), store, dashboard_access=dashboard_access).run()
    finally:
        if dashboard is not None:
            dashboard.stop()
        if daemon_pid_path is not None:
            _remove_pid_file(daemon_pid_path, daemon_pid)
