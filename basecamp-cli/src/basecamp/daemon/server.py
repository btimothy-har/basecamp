"""Daemon server runner."""

from __future__ import annotations

import os
import socket as socket_module
from pathlib import Path

import uvicorn

from basecamp.daemon.app import create_app
from basecamp.daemon.store import Store

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


def create_server(uds_path: str, store: Store, *, log_level: str = "info") -> UdsServer:
    """Build a UDS-bound daemon server for the given store."""

    app = create_app(store, daemon_uds=uds_path)
    config = uvicorn.Config(app, uds=uds_path, log_level=log_level)
    return UdsServer(config)


def run_daemon(uds_path: str, db_path: str | None = None) -> None:
    """Run the daemon bound to a Unix domain socket."""

    socket_path = Path(uds_path).expanduser()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    create_server(str(socket_path), Store(db_path=db_path)).run()
