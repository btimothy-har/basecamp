"""handle_wait must surface a wait_for_agents failure instead of swallowing it.

The correlated wait_result reply is always sent, but the bare except in
handle_wait used to report every requested handle as "unknown" with error=None
and log nothing. The fallback items must now carry the exception text so the
cause reaches the client, and the traceback is logged server-side.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app_helpers import _build_app_with_store, _register_ws
from fastapi.testclient import TestClient

import basecamp.hub.handlers as handlers_module
from basecamp.hub.frames import PROTOCOL_VERSION


def _seed_awaitable_run(store, *, dispatcher_id: str, agent_handle: str, agent_id: str) -> None:
    """Register an agent with a live non-terminal run owned by dispatcher_id."""
    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=agent_handle,
        parent_id=dispatcher_id,
        sibling_group=dispatcher_id,
        depth=1,
        role="worker",
        session_name=agent_handle,
        cwd=f"/tmp/{agent_id}",
    )
    store.create_run(
        run_id=f"run-{agent_id}",
        agent_id=agent_id,
        dispatcher_id=dispatcher_id,
        spec={"task": "x"},
        report_token_hash="hash",
    )


def test_ws_wait_failure_propagates_exception_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # When wait_for_agents raises, the requester still gets a correlated
    # wait_result — but every fallback item must now carry the cause (previously
    # error=None with no server-side log) so the failure is diagnosable. Both
    # the agent_handles and agent_ids branches of the fallback are exercised.
    app, store = _build_app_with_store(tmp_path)
    _seed_awaitable_run(store, dispatcher_id="node-1", agent_handle="amber-fox-a1b2c3", agent_id="agent-awaitable")

    def boom(**_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(handlers_module, "wait_for_agents", boom)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            _register_ws(ws, node_id="node-1", role="agent", parent_id=None, sibling_group="sg-main")
            ws.send_json(
                {
                    "type": "wait",
                    "v": PROTOCOL_VERSION,
                    "request_id": "wait-failing",
                    "agent_handles": ["amber-fox-a1b2c3"],
                    "agent_ids": ["agent-awaitable"],
                    "mode": "all",
                    "timeout_s": 1.0,
                }
            )
            reply = ws.receive_json()

    assert reply["type"] == "wait_result"
    assert reply["request_id"] == "wait-failing"
    assert reply["results"], "expected at least one fallback result item"
    for item in reply["results"]:
        assert item["status"] == "unknown"
        assert item["error"] is not None
        assert "boom" in item["error"]
        assert "wait failed" in item["error"]
