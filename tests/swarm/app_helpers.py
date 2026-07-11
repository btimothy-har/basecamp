"""Shared daemon-app test helpers: app builders and WS/HTTP payload utilities."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from basecamp.swarm.app import create_app
from basecamp.swarm.frames import PROTOCOL_VERSION
from basecamp.swarm.store import Store


class _RecordingScheduler:
    """Test double for the analysis scheduler: records calls, does no analysis.

    Keeps the app's ingest tests hermetic (no LLM, no alias-file read) while letting
    tests assert the daemon wakes the scheduler with the right node/seq.
    """

    def __init__(self) -> None:
        self.notified: list[tuple[str, int]] = []
        self.forgotten: list[str] = []

    def notify(self, owner_id: str, seq: int) -> None:
        self.notified.append((owner_id, seq))

    def forget(self, owner_id: str) -> None:
        self.forgotten.append(owner_id)

    async def stop(self) -> None:
        return None


def _build_app(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    return create_app(store, scheduler=_RecordingScheduler())


def _build_app_with_store(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    return create_app(store, scheduler=_RecordingScheduler()), store


def _build_app_with_scheduler(tmp_path: Path):
    store = Store(db_path=tmp_path / "daemon.db", task_dir=tmp_path / "tasks")
    scheduler = _RecordingScheduler()
    return create_app(store, scheduler=scheduler), store, scheduler


def _register_ws(
    websocket,
    *,
    node_id: str,
    role: str,
    parent_id: str | None,
    sibling_group: str | None,
    agent_handle: str | None = None,
) -> None:
    payload = {
        "type": "register",
        "v": PROTOCOL_VERSION,
        "role": role,
        "node_id": node_id,
        "parent_id": parent_id,
        "sibling_group": sibling_group,
        "depth": 0 if role == "session" else 1,
        "session_name": node_id,
        "cwd": f"/tmp/{node_id}",
    }
    if agent_handle is not None:
        payload["agent_handle"] = agent_handle
    websocket.send_json(payload)
    assert websocket.receive_json()["type"] == "registered"


def _peer_message(
    request_id: str,
    *,
    target_handle: str,
    message: str,
    interrupt: bool = False,
) -> dict[str, object]:
    return {
        "type": "peer_message",
        "v": PROTOCOL_VERSION,
        "request_id": request_id,
        "target_handle": target_handle,
        "message": message,
        "interrupt": interrupt,
    }


def _message_count(store: Store) -> int:
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute("SELECT COUNT(*) FROM messages").fetchone()
    assert row is not None
    return int(row[0])


def _message_status(
    message_id: str,
    *,
    request_id: str | None = None,
    wait_until_delivery: bool = False,
    timeout_s: float | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "message_status",
        "v": PROTOCOL_VERSION,
        "request_id": request_id or f"request-status-{message_id}",
        "message_id": message_id,
        "wait_until_delivery": wait_until_delivery,
    }
    if timeout_s is not None:
        payload["timeout_s"] = timeout_s
    return payload


def _start_message_status_wait(websocket, message_id: str, *, timeout_s: float) -> dict[str, object]:
    result: dict[str, object] = {}
    sent = threading.Event()

    def wait_for_status() -> None:
        websocket.send_json(_message_status(message_id, wait_until_delivery=True, timeout_s=timeout_s))
        sent.set()
        result.update(websocket.receive_json())

    thread = threading.Thread(target=wait_for_status)
    thread.start()
    return {"thread": thread, "sent": sent, "result": result}


def _wait_for_store_message_status(store: Store, message_id: str, status: str) -> dict[str, object]:
    deadline = time.time() + 2
    message = None
    while time.time() < deadline:
        message = store.get_message(message_id)
        if message is not None and message["status"] == status:
            return message
        time.sleep(0.01)
    assert message is not None
    assert message["status"] == status
    return message


def _unknown_message_status(message_id: str, request_id: str | None = None) -> dict[str, object]:
    return {
        "type": "message_status_result",
        "v": PROTOCOL_VERSION,
        "request_id": request_id or f"request-status-{message_id}",
        "message_id": message_id,
        "status": "unknown",
        "error": None,
        "created_at": None,
        "sent_at": None,
        "queued_at": None,
        "failed_at": None,
    }
