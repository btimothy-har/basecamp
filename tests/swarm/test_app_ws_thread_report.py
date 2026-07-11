"""Daemon app WS thread_report ingest tests (node by node)."""

from __future__ import annotations

import time
from pathlib import Path

from app_helpers import _build_app_with_store, _register_ws
from fastapi.testclient import TestClient

from basecamp.swarm.frames import PROTOCOL_VERSION
from basecamp.swarm.store import Store
from basecamp.swarm.store.raw_pi_thread import RawPiThreadRow


def _wait_for_head(store: Store, owner_id: str, timeout: float = 2.0) -> RawPiThreadRow | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        head = store.get_raw_pi_thread(owner_id)
        if head is not None:
            return head
        time.sleep(0.01)
    return None


def test_ws_thread_report_persists_nodes_and_session_pointers(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        _register_ws(websocket, node_id="session-1", role="session", parent_id=None, sibling_group="sg-1")
        websocket.send_json(
            {
                "type": "thread_report",
                "v": PROTOCOL_VERSION,
                "node_id": "session-1",
                "session_id": "pi-sess-1",
                "session_file": "/home/u/.pi/sessions/pi-sess-1.jsonl",
                "leaf_id": "e2",
                "nodes": [
                    {"id": "e1", "parent_id": None, "entry_json": "root"},
                    {"id": "e2", "parent_id": "e1", "entry_json": "leaf"},
                ],
            }
        )
        head = _wait_for_head(store, "session-1")

    assert head is not None
    assert head.session_id == "pi-sess-1"
    assert head.session_file == "/home/u/.pi/sessions/pi-sess-1.jsonl"
    assert head.leaf_id == "e2"
    assert store.get_raw_pi_thread_nodes("session-1").live == ["root", "leaf"]


def test_ws_thread_report_keyed_by_authenticated_connection_node(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)
    client = TestClient(app)

    with client.websocket_connect("/ws") as websocket:
        _register_ws(websocket, node_id="session-1", role="session", parent_id=None, sibling_group="sg-1")
        websocket.send_json(
            {
                "type": "thread_report",
                "v": PROTOCOL_VERSION,
                "node_id": "someone-else",
                "session_id": "pi",
                "session_file": None,
                "leaf_id": "e1",
                "nodes": [{"id": "e1", "parent_id": None, "entry_json": "x"}],
            }
        )
        head = _wait_for_head(store, "session-1")

    assert head is not None
    assert store.get_raw_pi_thread("someone-else") is None
