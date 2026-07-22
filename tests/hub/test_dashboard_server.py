"""Managed dashboard TCP listener lifecycle tests."""

from __future__ import annotations

import http.client
import socket
from pathlib import Path

from fastapi import FastAPI
from pytest import MonkeyPatch

from basecamp.hub.dashboard.access import DashboardAccess
from basecamp.hub.dashboard.app import DASHBOARD_HOST, DASHBOARD_PORT
from basecamp.hub.dashboard.server import DashboardServer


def test_dashboard_server_prebinds_loopback_and_stops_cleanly(tmp_path: Path) -> None:
    access = DashboardAccess()
    server = DashboardServer(access=access, uds_path=str(tmp_path / "daemon.sock"), port=0)

    try:
        assert server.start() is True
        assert server.host == "127.0.0.1"
        assert server.port > 0
        assert access.availability().base_url == f"http://127.0.0.1:{server.port}"
        assert server.thread is not None
        assert server.thread.daemon is True
        assert server.thread.is_alive()
        assert server.server is not None
        assert server.server.config.access_log is False
        assert server.server.config.server_header is False
        assert server.server.config.date_header is False
        assert server._listener is not None
        assert server._listener.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR) == 0
        if hasattr(socket, "SO_REUSEPORT"):
            assert server._listener.getsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT) == 0

        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        connection.request("GET", "/", headers={"Sec-Fetch-Site": "none"})
        response = connection.getresponse()
        response.read()
        connection.close()
        assert response.status == 401
        assert response.headers["Cache-Control"] == "no-store, max-age=0"
    finally:
        assert server.stop() is True

    assert access.availability().available is False
    assert server.thread is not None
    assert not server.thread.is_alive()
    assert server.stop() is True


def test_dashboard_server_uses_fixed_production_endpoint() -> None:
    server = DashboardServer(access=DashboardAccess(), uds_path="/tmp/daemon.sock")
    assert server.host == DASHBOARD_HOST == "127.0.0.1"
    assert server.port == DASHBOARD_PORT == 47658


def test_dashboard_port_collision_is_nonfatal() -> None:
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = int(occupied.getsockname()[1])
    access = DashboardAccess()
    server = DashboardServer(access=access, uds_path="/tmp/daemon.sock", port=port)

    try:
        assert server.start() is False
        availability = access.availability()
        assert availability.available is False
        assert availability.reason == f"dashboard port 127.0.0.1:{port} is already in use"
        assert server.thread is None
    finally:
        occupied.close()
        server.stop()


def test_dashboard_thread_start_failure_closes_listener(monkeypatch: MonkeyPatch) -> None:
    class FailingThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError

    monkeypatch.setattr("basecamp.hub.dashboard.server.threading.Thread", FailingThread)
    access = DashboardAccess()
    server = DashboardServer(access=access, uds_path="/tmp/daemon.sock", port=0)

    assert server.start() is False
    failed_port = server.port
    assert failed_port > 0
    assert server.thread is None
    assert access.availability().reason == f"dashboard listener failed to start on 127.0.0.1:{failed_port}"
    replacement = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        replacement.bind(("127.0.0.1", failed_port))
    finally:
        replacement.close()


def test_dashboard_app_construction_failure_is_nonfatal() -> None:
    def fail_app(**_kwargs: object) -> FastAPI:
        raise RuntimeError

    access = DashboardAccess()
    server = DashboardServer(
        access=access,
        uds_path="/tmp/daemon.sock",
        port=0,
        app_factory=fail_app,
    )

    assert server.start() is False
    assert access.availability().available is False
    assert access.availability().reason == "dashboard listener failed to start on 127.0.0.1:0"
    assert server.stop() is True
