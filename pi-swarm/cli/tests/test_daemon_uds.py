"""UDS and daemon server runner tests."""

from __future__ import annotations

import os
import stat
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import uvicorn
from pi_swarm import main as swarm_cli
from pi_swarm import server as daemon_server
from pi_swarm.app import create_app
from pi_swarm.server import UdsServer
from pi_swarm.store import Store
from pytest import MonkeyPatch


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


class _FakeServer:
    def __init__(self, on_run: Callable[[], None]) -> None:
        self._on_run = on_run

    def run(self) -> None:
        self._on_run()


def test_bc_swarm_daemon_cli_invokes_run_daemon(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    uds_path = tmp_path / "daemon.sock"
    db_path = tmp_path / "daemon.db"
    pid_path = tmp_path / "daemon.pid"
    observed: dict[str, tuple[str, str | None, str | None]] = {}

    def run_daemon(uds_path_arg: str, db_path_arg: str | None = None, pid_path_arg: str | None = None) -> None:
        observed["args"] = (uds_path_arg, db_path_arg, pid_path_arg)

    monkeypatch.setattr(swarm_cli, "run_daemon", run_daemon)

    swarm_cli.main(
        [
            "daemon",
            "--uds",
            str(uds_path),
            "--db",
            str(db_path),
            "--pidfile",
            str(pid_path),
        ]
    )

    assert observed["args"] == (str(uds_path), str(db_path), str(pid_path))


def test_run_daemon_writes_and_removes_pid_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    uds_path = tmp_path / "daemon.sock"
    observed_pid_files: list[str] = []

    def create_server(uds_path_arg: str, store: Store) -> _FakeServer:
        assert uds_path_arg == str(uds_path)
        assert isinstance(store, Store)
        return _FakeServer(lambda: observed_pid_files.append(pid_path.read_text(encoding="utf-8")))

    monkeypatch.setattr(daemon_server, "create_server", create_server)

    daemon_server.run_daemon(str(uds_path), pid_path=str(pid_path))

    assert observed_pid_files == [f"{os.getpid()}\n"]
    assert not pid_path.exists()


def test_run_daemon_does_not_remove_replaced_pid_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    uds_path = tmp_path / "daemon.sock"
    replacement = "999999\n"

    def create_server(_uds_path_arg: str, _store: Store) -> _FakeServer:
        return _FakeServer(lambda: pid_path.write_text(replacement, encoding="utf-8"))

    monkeypatch.setattr(daemon_server, "create_server", create_server)

    daemon_server.run_daemon(str(uds_path), pid_path=str(pid_path))

    assert pid_path.read_text(encoding="utf-8") == replacement


def test_health_over_real_uds(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    uds_path = Path("/tmp") / f"basecamp-daemon-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    if uds_path.exists():
        uds_path.unlink()

    app = create_app(Store(db_path=db_path))

    config = uvicorn.Config(app=app, uds=str(uds_path), log_level="error")
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.time() + 5
    while time.time() < deadline and not uds_path.exists():
        time.sleep(0.05)

    transport = httpx.HTTPTransport(uds=str(uds_path))
    try:
        deadline = time.time() + 5
        response = None
        while time.time() < deadline:
            try:
                with httpx.Client(transport=transport, base_url="http://daemon") as client:
                    response = client.get("/health")
                break
            except (httpx.ConnectError, FileNotFoundError):
                time.sleep(0.05)

        assert response is not None
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "protocol": 4}

        socket_mode = stat.S_IMODE(uds_path.stat().st_mode)
        assert socket_mode == 0o600, f"socket perms {socket_mode:o} should be 0600 (local-user only)"
    finally:
        transport.close()
        server.should_exit = True
        thread.join(timeout=5)
        if uds_path.exists():
            uds_path.unlink()
