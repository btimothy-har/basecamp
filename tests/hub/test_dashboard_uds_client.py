"""Allowlisted dashboard UDS client tests."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from basecamp.hub.app import create_app
from basecamp.hub.dashboard.access import DashboardAccess
from basecamp.hub.dashboard.uds import DashboardUdsClient, DashboardUdsError
from basecamp.hub.server import UdsServer
from basecamp.hub.store import Store


class _Response:
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self._body = json.dumps(payload).encode()

    def read(self, _limit: int) -> bytes:
        return self._body


class _Connection:
    responses: list[_Response] = []
    requests: list[tuple[str, str, bytes | None]] = []

    def __init__(self, _uds_path: str, *, timeout: float) -> None:
        self.timeout = timeout

    def request(self, method: str, path: str, *, body: bytes | None, headers: dict[str, str]) -> None:
        assert headers == {"Accept": "application/json"}
        self.requests.append((method, path, body))

    def getresponse(self) -> _Response:
        return self.responses.pop(0)

    def close(self) -> None:
        pass


def test_dashboard_uds_client_uses_only_fixed_paths() -> None:
    _Connection.requests = []
    _Connection.responses = [
        _Response(200, {"roots": []}),
        _Response(200, {"messages": []}),
        _Response(200, {"url": "http://127.0.0.1:47658/bootstrap/nonce"}),
    ]
    client = DashboardUdsClient("/tmp/daemon.sock", connection_factory=_Connection)

    assert client.get_snapshot() == {"roots": []}
    assert client.get_messages(root_handle="root one", agent_handle="agent/two") == {"messages": []}
    assert client.mint_bootstrap_url() == "http://127.0.0.1:47658/bootstrap/nonce"
    assert _Connection.requests == [
        ("GET", "/dashboard/snapshot", None),
        ("GET", "/dashboard/messages?root_handle=root+one&agent_handle=agent%2Ftwo", None),
        ("POST", "/dashboard/bootstrap", b""),
    ]


def test_dashboard_uds_client_round_trips_real_private_socket(tmp_path: Path) -> None:
    uds_path = Path("/tmp") / f"basecamp-dashboard-{os.getpid()}-{uuid.uuid4().hex[:8]}.sock"
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    store.upsert_agent(
        agent_id="root-private",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root",
        cwd="/private/root",
    )
    access = DashboardAccess(token_factory=lambda: "n" * 43)
    access.set_available("http://127.0.0.1:47658")
    server = UdsServer(
        uvicorn.Config(
            create_app(store, daemon_uds=str(uds_path), dashboard_access=access),
            uds=str(uds_path),
            log_level="error",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    client = DashboardUdsClient(str(uds_path), timeout=0.2)

    try:
        deadline = time.monotonic() + 5
        snapshot = None
        while time.monotonic() < deadline:
            try:
                snapshot = client.get_snapshot()
                break
            except DashboardUdsError:
                time.sleep(0.02)
        assert snapshot is not None
        assert [root["root_handle"] for root in snapshot["roots"]] == ["root-handle"]
        assert client.mint_bootstrap_url() == f"http://127.0.0.1:47658/bootstrap/{'n' * 43}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        if uds_path.exists():
            uds_path.unlink()


def test_dashboard_uds_client_preserves_bounded_error_detail() -> None:
    _Connection.requests = []
    _Connection.responses = [_Response(503, {"detail": "dashboard port is occupied"})]
    client = DashboardUdsClient("/tmp/daemon.sock", connection_factory=_Connection)

    with pytest.raises(DashboardUdsError) as raised:
        client.mint_bootstrap_url()

    assert raised.value.status == 503
    assert raised.value.detail == "dashboard port is occupied"
