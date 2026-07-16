"""Transport tests: health-ping parsing (mocked) + register/end over a real UDS."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn

from basecamp.hub.app import create_app
from basecamp.hub.client import transport as transport_mod
from basecamp.hub.client.identity import build_register_frame
from basecamp.hub.client.paths import DaemonPaths
from basecamp.hub.client.sessions import end_session, register_session
from basecamp.hub.client.transport import HealthResult, health_ping
from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.server import UdsServer
from basecamp.hub.store import Store


class _ThreadedServer(UdsServer):
    def install_signal_handlers(self) -> None:  # noqa: D401
        """No signal handlers when running under a background thread."""


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> Callable[[str, float], httpx.Client]:
    def factory(_socket_path: str, timeout: float) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://daemon", timeout=timeout)

    return factory


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    monkeypatch.setattr(transport_mod, "_client", _mock_client(handler))


def test_health_ping_ok_returns_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock(monkeypatch, lambda _r: httpx.Response(200, json={"status": "ok", "protocol": 23}))
    assert health_ping("/sock") == HealthResult(ok=True, protocol=23)


def test_health_ping_missing_protocol_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock(monkeypatch, lambda _r: httpx.Response(200, json={"status": "ok"}))
    assert health_ping("/sock") == HealthResult(ok=False)


def test_health_ping_bad_status_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock(monkeypatch, lambda _r: httpx.Response(200, json={"status": "degraded", "protocol": 23}))
    assert health_ping("/sock") == HealthResult(ok=False)


def test_health_ping_non_200_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock(monkeypatch, lambda _r: httpx.Response(503, json={"status": "ok", "protocol": 23}))
    assert health_ping("/sock") == HealthResult(ok=False)


def test_health_ping_non_json_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mock(monkeypatch, lambda _r: httpx.Response(200, text="not json"))
    assert health_ping("/sock") == HealthResult(ok=False)


def test_health_ping_connection_error_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(request: httpx.Request) -> httpx.Response:
        msg = "no daemon"
        raise httpx.ConnectError(msg, request=request)

    _install_mock(monkeypatch, _raise)
    assert health_ping("/sock") == HealthResult(ok=False)


@contextmanager
def _running_daemon(tmp_path: Path) -> Iterator[tuple[DaemonPaths, Store]]:
    uds_path = Path("/tmp") / f"basecamp-client-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    uds_path.unlink(missing_ok=True)
    store = Store(db_path=tmp_path / "daemon.db")
    config = uvicorn.Config(app=create_app(store), uds=str(uds_path), log_level="error")
    server = _ThreadedServer(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not health_ping(str(uds_path)).ok:
            time.sleep(0.05)
        paths = DaemonPaths(
            runtime_dir=tmp_path,
            socket=uds_path,
            spawn_lock=tmp_path / "daemon.spawn.lock",
            pidfile=tmp_path / "daemon.pid",
            db=tmp_path / "daemon.db",
        )
        yield paths, store
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        uds_path.unlink(missing_ok=True)


def test_register_and_end_session_over_uds(tmp_path: Path) -> None:
    with _running_daemon(tmp_path) as (paths, store):
        assert health_ping(str(paths.socket)) == HealthResult(ok=True, protocol=PROTOCOL_VERSION)

        frame = build_register_frame(
            session_id="sess-e2e",
            cwd="/work/e2e",
            transcript_path="/transcripts/e2e.jsonl",
            env={"BASECAMP_REPO": "test/e2e"},
        )
        outcome = register_session(frame, paths=paths)
        assert outcome.status == 200
        assert outcome.body["status"] == "registered"
        assert [row["id"] for row in store.list_open_sessions()] == ["sess-e2e"]

        assert end_session("sess-e2e", paths=paths) is True
        assert store.list_open_sessions() == []


def test_end_session_returns_false_when_daemon_absent(tmp_path: Path) -> None:
    paths = DaemonPaths(
        runtime_dir=tmp_path,
        socket=tmp_path / "absent.sock",
        spawn_lock=tmp_path / "daemon.spawn.lock",
        pidfile=tmp_path / "daemon.pid",
        db=tmp_path / "daemon.db",
    )
    assert end_session("sess-x", paths=paths) is False
