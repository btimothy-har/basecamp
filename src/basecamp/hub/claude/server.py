"""Runner for the Claude Code session-lifecycle hub daemon.

Self-contained on purpose: the Claude section owns its own UDS-hardening server
harness so it depends on nothing in the Pi runtime (``basecamp.hub.server`` would
drag in the swarm app graph). The harness mirrors the Pi daemon's — tighten the
socket to owner-only after bind, write/clean a pidfile — but over the minimal
Claude app. At promotion this file simply becomes *the* hub server.
"""

from __future__ import annotations

import os
import socket as socket_module
from pathlib import Path

import uvicorn

from .app import create_claude_app
from .store import SessionStore

_SOCKET_MODE = 0o600


class UdsServer(uvicorn.Server):
    """uvicorn server that tightens the UDS to owner-only after binding.

    uvicorn binds the socket and chmods it to 0666 inside ``startup()``; doing the
    restriction afterwards is the only reliable point and preserves the
    local-user-only trust boundary (the lifespan hook runs before the bind).
    """

    async def startup(self, sockets: list[socket_module.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        uds = self.config.uds
        if not uds:
            return
        try:
            os.chmod(uds, _SOCKET_MODE)
        except OSError as exc:
            # Fail fast: serving on a socket we couldn't restrict to 0600 would
            # break the local-user-only trust boundary.
            msg = f"failed to restrict daemon socket {uds} to {oct(_SOCKET_MODE)}"
            raise RuntimeError(msg) from exc


def create_server(uds_path: str, store: SessionStore, *, log_level: str = "info") -> UdsServer:
    """Build a UDS-bound Claude daemon server for ``store``."""

    config = uvicorn.Config(create_claude_app(store), uds=uds_path, log_level=log_level)
    return UdsServer(config)


def _write_pid_file(pid_path: Path, pid: int) -> None:
    pid_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
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


def run_claude_hub(
    uds_path: str,
    db_path: str | None = None,
    pid_path: str | None = None,
) -> None:
    """Run the Claude hub daemon bound to a Unix domain socket."""

    socket_path = Path(uds_path).expanduser()
    socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if socket_path.exists():
        socket_path.unlink()

    daemon_pid = os.getpid()
    daemon_pid_path = Path(pid_path).expanduser() if pid_path is not None else None
    if daemon_pid_path is not None:
        _write_pid_file(daemon_pid_path, daemon_pid)

    try:
        store = SessionStore(db_path=db_path)
        create_server(str(socket_path), store).run()
    finally:
        if daemon_pid_path is not None:
            _remove_pid_file(daemon_pid_path, daemon_pid)
