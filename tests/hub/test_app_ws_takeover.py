"""Duplicate-register takeover: liveness gating and generation-guarded cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest
from app_helpers import _build_app, _register_ws
from fastapi.testclient import TestClient

from basecamp.hub.frames import PROTOCOL_VERSION
from basecamp.hub.registry import Registry


def test_ws_duplicate_register_live_incumbent_rejected(tmp_path: Path) -> None:
    # A live incumbent keeps its session: the duplicate register probes it, the
    # write succeeds, and the newcomer gets the same rejection as before.
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            # The incumbent receives the liveness probe (a ping frame) while its
            # duplicate is being classified; drain it so the read below is the error.
            with client.websocket_connect("/ws") as second:
                second.send_json(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "agent",
                        "node_id": "node-1",
                        "parent_id": None,
                        "sibling_group": "sg-main",
                        "depth": 0,
                        "session_name": "resume-session",
                        "cwd": "/tmp/project",
                    }
                )
                assert first.receive_json()["type"] == "ping"
                reply = second.receive_json()
                assert reply["type"] == "error"
                assert reply["code"] == "duplicate_node_connection"
            # The incumbent is still usable afterwards.
            first.send_json(
                {
                    "type": "list_agents",
                    "v": PROTOCOL_VERSION,
                    "request_id": "req-after-dup",
                    "awaitable": False,
                }
            )
            assert first.receive_json()["type"] == "list_agents_result"


def test_ws_duplicate_register_dead_incumbent_takeover(tmp_path: Path) -> None:
    # A provably dead incumbent yields its node id: the probe write fails and
    # the new registration completes — the resume-after-unclean-exit path.
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            first.close()
            # The server handler for the first socket has not yet observed the
            # close: register the replacement immediately.
            with client.websocket_connect("/ws") as second:
                _register_ws(second, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")


def test_ws_takeover_stale_cleanup_does_not_reap_new_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A zombie incumbent's handler can run its cleanup only after the
    # replacement has already registered. Generation-guarded removal must make
    # that stale cleanup a no-op: the newer registry entry survives and no
    # disconnect reaper is scheduled for it. Observed registry trace of this
    # exact scenario: gen1 remove-True + reaper (the takeover close, while gen1
    # was still the entry) -> gen2 set -> gen2 remove-True + reaper (the second
    # socket's own close) — i.e. exactly one reaper per generation, and a
    # regression that let the stale cleanup remove gen2 would add a third.
    reaped: list[str] = []
    monkeypatch.setattr(
        "basecamp.hub.app.schedule_disconnect_reaper",
        lambda **kwargs: reaped.append(str(kwargs["node_id"])),
    )
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as first:
            _register_ws(first, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            first.close()
            with client.websocket_connect("/ws") as second:
                _register_ws(second, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")

    assert reaped == ["node-1", "node-1"]


def test_ws_ping_answered_with_pong_and_pong_ignored(tmp_path: Path) -> None:
    # Keepalive contract: ping gets a pong with the same nonce; an unsolicited
    # pong is inert (the connection simply continues).
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            ws.send_json({"type": "pong", "v": PROTOCOL_VERSION, "nonce": "unsolicited"})
            ws.send_json({"type": "ping", "v": PROTOCOL_VERSION, "nonce": "nonce-42"})
            reply = ws.receive_json()
            assert reply == {"type": "pong", "v": PROTOCOL_VERSION, "nonce": "nonce-42"}
            ws.send_json(
                {
                    "type": "list_agents",
                    "v": PROTOCOL_VERSION,
                    "request_id": "req-after-ping",
                    "awaitable": False,
                }
            )
            assert ws.receive_json()["type"] == "list_agents_result"


def test_ws_wait_does_not_block_connection_read_loop(tmp_path: Path) -> None:
    # v28: a wait in flight runs as a daemon-side task — the same socket keeps
    # answering pings and processing other frames instead of freezing for the
    # wait's full timeout.
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            ws.send_json(
                {
                    "type": "wait",
                    "v": PROTOCOL_VERSION,
                    "request_id": "wait-block-1",
                    "agent_handles": ["nonexistent-agent"],
                    "mode": "all",
                    "timeout_s": 30,
                }
            )
            # With an unknown handle the wait resolves immediately; assert the
            # echo and that the loop is already responsive right after it.
            ws.send_json({"type": "ping", "v": PROTOCOL_VERSION, "nonce": "during-wait"})
            replies = sorted(
                (ws.receive_json(), ws.receive_json()),
                key=lambda frame: frame["type"],
            )
            assert replies[0]["type"] == "pong"
            assert replies[1]["type"] == "wait_result"
            assert replies[1]["request_id"] == "wait-block-1"


def test_registry_remove_connection_generation_guard() -> None:
    registry = Registry()
    first_gen = registry.set_connection("node-1", object())
    second_gen = registry.set_connection("node-1", object())
    assert second_gen > first_gen

    assert registry.remove_connection("node-1", generation=first_gen) is False
    assert registry.get_connection_generation("node-1") == second_gen
    assert registry.is_connection_current("node-1", second_gen) is True
    assert registry.is_connection_current("node-1", first_gen) is False

    assert registry.remove_connection("node-1", generation=second_gen) is True
    assert registry.get_connection("node-1") is None
    assert registry.remove_connection("node-1", generation=second_gen) is False
