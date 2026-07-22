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
from pytest import MonkeyPatch, raises

from basecamp.hub import server as daemon_server
from basecamp.hub.app import create_app
from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.server import UdsServer
from basecamp.hub.store import Store


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """Disable signal handlers when running under a background thread."""


class _FakeServer:
    def __init__(self, on_run: Callable[[], None]) -> None:
        self._on_run = on_run

    def run(self) -> None:
        self._on_run()


class _FakeDashboardServer:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True


def _stub_dashboard(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(daemon_server, "DashboardServer", _FakeDashboardServer)


def test_server_lock_is_exclusive_and_reusable(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.server.lock"
    first = daemon_server._acquire_server_lock(lock_path)
    try:
        with raises(daemon_server.HubAlreadyRunningError):
            daemon_server._acquire_server_lock(lock_path)
        socket_path = tmp_path / "daemon.sock"
        socket_path.write_text("live socket placeholder", encoding="utf-8")
        with raises(daemon_server.HubAlreadyRunningError):
            daemon_server.run_hub(str(socket_path))
        assert socket_path.read_text(encoding="utf-8") == "live socket placeholder"
    finally:
        daemon_server._release_server_lock(first)

    replacement = daemon_server._acquire_server_lock(lock_path)
    daemon_server._release_server_lock(replacement)
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600


def test_run_hub_writes_and_removes_pid_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    uds_path = tmp_path / "daemon.sock"
    db_path = tmp_path / "daemon.db"
    observed_pid_files: list[str] = []

    def create_server(uds_path_arg: str, store: Store, **_kwargs: object) -> _FakeServer:
        assert uds_path_arg == str(uds_path)
        assert isinstance(store, Store)
        return _FakeServer(lambda: observed_pid_files.append(pid_path.read_text(encoding="utf-8")))

    monkeypatch.setattr(daemon_server, "create_server", create_server)
    _stub_dashboard(monkeypatch)

    daemon_server.run_hub(str(uds_path), db_path=str(db_path), pid_path=str(pid_path))

    assert observed_pid_files == [f"{os.getpid()}\n"]
    assert not pid_path.exists()


def test_run_hub_does_not_remove_replaced_pid_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    uds_path = tmp_path / "daemon.sock"
    db_path = tmp_path / "daemon.db"
    replacement = "999999\n"

    def create_server(_uds_path_arg: str, _store: Store, **_kwargs: object) -> _FakeServer:
        return _FakeServer(lambda: pid_path.write_text(replacement, encoding="utf-8"))

    monkeypatch.setattr(daemon_server, "create_server", create_server)
    _stub_dashboard(monkeypatch)

    daemon_server.run_hub(str(uds_path), db_path=str(db_path), pid_path=str(pid_path))

    assert pid_path.read_text(encoding="utf-8") == replacement


def test_run_hub_reconciles_before_serving(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    uds_path = tmp_path / "daemon.sock"
    db_path = tmp_path / "daemon.db"
    events: list[str] = []

    def reconcile_orphaned_runs(store: Store) -> None:
        assert isinstance(store, Store)
        events.append("reconcile")

    def create_server(uds_path_arg: str, store: Store, **_kwargs: object) -> _FakeServer:
        assert uds_path_arg == str(uds_path)
        assert isinstance(store, Store)
        events.append("create_server")
        return _FakeServer(lambda: events.append("run"))

    monkeypatch.setattr(daemon_server, "reconcile_orphaned_runs", reconcile_orphaned_runs)
    monkeypatch.setattr(daemon_server, "create_server", create_server)
    _stub_dashboard(monkeypatch)

    daemon_server.run_hub(str(uds_path), db_path=str(db_path), pid_path=str(pid_path))

    assert events == ["reconcile", "create_server", "run"]
    assert not pid_path.exists()


def test_run_hub_continues_and_stops_dashboard_after_nonfatal_start_failure(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    events: list[str] = []

    class FailingDashboard:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> bool:
            events.append("dashboard_start")
            return False

        def stop(self) -> bool:
            events.append("dashboard_stop")
            return True

    def create_server(_uds_path: str, _store: Store, **_kwargs: object) -> _FakeServer:
        return _FakeServer(lambda: events.append("uds_run"))

    monkeypatch.setattr(daemon_server, "DashboardServer", FailingDashboard)
    monkeypatch.setattr(daemon_server, "create_server", create_server)

    daemon_server.run_hub(str(tmp_path / "daemon.sock"), db_path=str(tmp_path / "daemon.db"))

    assert events == ["dashboard_start", "uds_run", "dashboard_stop"]


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
        assert response.json() == {"status": "ok", "protocol": PROTOCOL_VERSION}

        socket_mode = stat.S_IMODE(uds_path.stat().st_mode)
        assert socket_mode == 0o600, f"socket perms {socket_mode:o} should be 0600 (local-user only)"
    finally:
        transport.close()
        server.should_exit = True
        thread.join(timeout=5)
        if uds_path.exists():
            uds_path.unlink()
