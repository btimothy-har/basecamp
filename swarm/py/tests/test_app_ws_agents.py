"""Daemon app WS agent directory, cancel, and workstream flow tests."""

from __future__ import annotations

from pathlib import Path

from app_helpers import _build_app, _build_app_with_store, _register_ws
from basecamp.swarm.frames import PROTOCOL_VERSION
from fastapi.testclient import TestClient


def test_ws_list_agents_returns_same_root_non_session_rows_and_awaitable_filters(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="agent",
        session_name="agent-one",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="agent",
        session_name="agent-two",
        cwd="/tmp/a2",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-out",
        depth=0,
        role="session",
        session_name="outside-session",
        cwd="/tmp/out",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-out-a",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/out-a",
    )

    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "a1"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-2",
        agent_id="agent-2",
        dispatcher_id="agent-1",
        spec={"task": "a2"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-2",
        status="completed",
        result="done",
        error=None,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as session_ws:
            session_ws.send_json(
                {
                    "type": "register",
                    "v": PROTOCOL_VERSION,
                    "role": "session",
                    "node_id": "root",
                    "parent_id": None,
                    "sibling_group": "sg-root",
                    "depth": 0,
                    "session_name": "root-session",
                    "cwd": "/tmp/root",
                }
            )
            session_ws.receive_json()

            with client.websocket_connect("/ws") as agent_ws:
                agent_ws.send_json(
                    {
                        "type": "register",
                        "v": PROTOCOL_VERSION,
                        "role": "agent",
                        "node_id": "agent-1",
                        "parent_id": "root",
                        "sibling_group": "sg-a1",
                        "depth": 1,
                        "session_name": "agent-one",
                        "cwd": "/tmp/a1",
                    }
                )
                agent_ws.receive_json()

                agent_ws.send_json(
                    {
                        "type": "list_agents",
                        "v": PROTOCOL_VERSION,
                        "request_id": "list-all",
                        "awaitable": False,
                    }
                )
                list_all = agent_ws.receive_json()
                assert list_all == {
                    "type": "list_agents_result",
                    "v": PROTOCOL_VERSION,
                    "request_id": "list-all",
                    "agents": [
                        {
                            "agent_id": "agent-1",
                            "agent_handle": "agent-1",
                            "parent_id": "root",
                            "role": "agent",
                            "session_name": "agent-one",
                            "depth": 1,
                            "status": "running",
                            "awaitable": False,
                            "task": "a1",
                        },
                        {
                            "agent_id": "agent-2",
                            "agent_handle": "agent-2",
                            "parent_id": "agent-1",
                            "role": "agent",
                            "session_name": "agent-two",
                            "depth": 2,
                            "status": "completed",
                            "awaitable": True,
                            "task": "a2",
                        },
                    ],
                }

                agent_ws.send_json(
                    {
                        "type": "list_agents",
                        "v": PROTOCOL_VERSION,
                        "request_id": "list-awaitable",
                        "awaitable": True,
                    }
                )
                list_awaitable = agent_ws.receive_json()
                assert list_awaitable == {
                    "type": "list_agents_result",
                    "v": PROTOCOL_VERSION,
                    "request_id": "list-awaitable",
                    "agents": [
                        {
                            "agent_id": "agent-2",
                            "agent_handle": "agent-2",
                            "parent_id": "agent-1",
                            "role": "agent",
                            "session_name": "agent-two",
                            "depth": 2,
                            "status": "completed",
                            "awaitable": True,
                            "task": "a2",
                        }
                    ],
                }


def test_ws_cancel_unknown_handle_returns_not_found_ack(tmp_path: Path) -> None:
    app = _build_app(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            _register_ws(websocket, node_id="root", role="session", parent_id=None, sibling_group="sg-root")
            websocket.send_json(
                {
                    "type": "cancel",
                    "v": PROTOCOL_VERSION,
                    "request_id": "cancel-missing",
                    "target_handle": "missing-handle",
                }
            )
            reply = websocket.receive_json()

    assert reply == {
        "type": "cancel_ack",
        "v": PROTOCOL_VERSION,
        "request_id": "cancel-missing",
        "status": "not_found",
        "error": None,
    }


def test_ws_workstream_create_attach_update_flow(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="root", role="session", parent_id=None, sibling_group="sg-root")

            ws.send_json(
                {
                    "type": "create_workstream",
                    "v": PROTOCOL_VERSION,
                    "request_id": "create-1",
                    "workstream_id": "ws-1",
                    "slug": "feature-auth",
                    "label": "Feature Auth",
                    "brief": "Implement auth",
                    "source_dossier_path": "/dossiers/auth.md",
                }
            )
            created = ws.receive_json()
            assert created == {
                "type": "create_workstream_ack",
                "v": PROTOCOL_VERSION,
                "request_id": "create-1",
                "status": "created",
                "workstream_id": "ws-1",
                "slug": "feature-auth",
                "error": None,
            }

            ws.send_json(
                {
                    "type": "create_workstream",
                    "v": PROTOCOL_VERSION,
                    "request_id": "create-2",
                    "workstream_id": "ws-2",
                    "slug": "feature-auth",
                    "label": "Feature Auth 2",
                    "brief": "Implement auth again",
                    "source_dossier_path": "/dossiers/auth2.md",
                }
            )
            conflict = ws.receive_json()
            assert conflict["type"] == "create_workstream_ack"
            assert conflict["request_id"] == "create-2"
            assert conflict["status"] == "slug_conflict"

            ws.send_json(
                {
                    "type": "attach_workstream_agent",
                    "v": PROTOCOL_VERSION,
                    "request_id": "attach-1",
                    "workstream": "feature-auth",
                }
            )
            attached = ws.receive_json()
            assert attached == {
                "type": "attach_workstream_agent_ack",
                "v": PROTOCOL_VERSION,
                "request_id": "attach-1",
                "status": "attached",
                "error": None,
            }

            ws.send_json(
                {
                    "type": "update_workstream",
                    "v": PROTOCOL_VERSION,
                    "request_id": "update-1",
                    "workstream": "feature-auth",
                    "status": "closed",
                }
            )
            updated = ws.receive_json()
            assert updated == {
                "type": "update_workstream_ack",
                "v": PROTOCOL_VERSION,
                "request_id": "update-1",
                "status": "updated",
                "error": None,
            }

            ws.send_json(
                {
                    "type": "update_workstream",
                    "v": PROTOCOL_VERSION,
                    "request_id": "update-2",
                    "workstream": "unknown-slug",
                    "status": "closed",
                }
            )
            update_not_found = ws.receive_json()
            assert update_not_found["type"] == "update_workstream_ack"
            assert update_not_found["status"] == "not_found"

            ws.send_json(
                {
                    "type": "attach_workstream_agent",
                    "v": PROTOCOL_VERSION,
                    "request_id": "attach-2",
                    "workstream": "unknown-slug",
                }
            )
            attach_not_found = ws.receive_json()
            assert attach_not_found["type"] == "attach_workstream_agent_ack"
            assert attach_not_found["status"] == "not_found"

        ws_row = store.get_workstream_with_agents("feature-auth")
        assert ws_row is not None
        assert ws_row["status"] == "closed"
        agent_ids = [agent["agent_id"] for agent in ws_row["agents"]]
        assert "root" in agent_ids


def test_http_workstreams_list_and_detail(tmp_path: Path) -> None:
    app, store = _build_app_with_store(tmp_path)

    store.create_workstream(
        workstream_id="ws-1",
        slug="feature-auth",
        label="Feature Auth",
        brief="Implement auth",
        source_dossier_path="/dossiers/auth.md",
    )
    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.attach_workstream_agent(
        workstream_id="ws-1",
        agent_id="root",
        repo="org/repo",
        worktree_label="wt-bt/auth",
    )

    with TestClient(app) as client:
        list_response = client.get("/workstreams")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload["workstreams"]) == 1
        assert payload["workstreams"][0]["slug"] == "feature-auth"

        detail_response = client.get("/workstreams/feature-auth")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["slug"] == "feature-auth"
        assert isinstance(detail["agents"], list)
        assert any(agent["agent_id"] == "root" for agent in detail["agents"])

        not_found_response = client.get("/workstreams/unknown-slug")
        assert not_found_response.status_code == 404
