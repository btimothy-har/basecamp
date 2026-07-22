"""Tests for dashboard assistant-message lookup by public handles."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.hub.store import Store
from basecamp.hub.store.dashboard import DASHBOARD_MESSAGE_CHARS


def _add_agent(
    store: Store,
    agent_id: str,
    handle: str,
    *,
    parent_id: str | None,
    role: str,
    depth: int,
) -> None:
    store.upsert_agent(
        agent_id=agent_id,
        agent_handle=handle,
        parent_id=parent_id,
        sibling_group=parent_id,
        depth=depth,
        role=role,
        session_name=handle,
        cwd=f"/private/{agent_id}",
        agent_type=None if role == "agent" else "scout",
    )


def test_dashboard_messages_are_scoped_bounded_and_assistant_only(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    _add_agent(store, "root-private", "root-handle", parent_id=None, role="agent", depth=0)
    _add_agent(store, "agent-private", "agent-handle", parent_id="root-private", role="worker", depth=1)
    _add_agent(store, "other-root-private", "other-root", parent_id=None, role="agent", depth=0)
    _add_agent(
        store,
        "other-agent-private",
        "other-agent",
        parent_id="other-root-private",
        role="worker",
        depth=1,
    )
    store.create_run(
        run_id="run-private",
        agent_id="agent-private",
        dispatcher_id="root-private",
        spec={"prompt": "PROMPT_SECRET", "env": {"KEY": "ENV_SECRET"}},
        report_token_hash="TOKEN_SECRET",
    )
    store.create_run(
        run_id="other-run-private",
        agent_id="other-agent-private",
        dispatcher_id="other-root-private",
        spec={},
    )
    store.append_run_event(run_id="run-private", kind="assistant_output", payload={"text": "first"})
    store.append_run_event(run_id="run-private", kind="assistant_output", payload={"text": "second"})
    store.append_run_event(
        run_id="run-private",
        kind="assistant_output",
        payload={"text": "x" * (DASHBOARD_MESSAGE_CHARS + 50), "label": "long output"},
    )
    store.append_run_event(
        run_id="run-private",
        kind="assistant_output",
        payload={"text": "<script>alert('escaped by renderer')</script>"},
    )
    store.append_run_event(
        run_id="run-private",
        kind="tool_result",
        payload={"text": "TOOL_SECRET", "raw": "RAW_SECRET"},
    )
    store.set_run_result(
        run_id="run-private",
        status="completed",
        result="FULL_RESULT_SECRET",
        error=None,
    )
    store.append_run_event(
        run_id="other-run-private",
        kind="assistant_output",
        payload={"text": "OUTSIDE_SECRET"},
    )

    result = store.get_dashboard_messages(root_handle="root-handle", agent_handle="agent-handle")

    assert result["root_handle"] == "root-handle"
    assert result["agent_handle"] == "agent-handle"
    assert len(result["messages"]) == 3
    assert result["messages"][0]["text"] == "second"
    assert len(result["messages"][1]["text"]) == DASHBOARD_MESSAGE_CHARS
    assert result["messages"][1]["truncated"] is True
    assert result["messages"][2]["text"].startswith("<script>")
    assert set(result["messages"][0]) == {"kind", "seq", "timestamp", "label", "text", "truncated"}
    serialized = json.dumps(result)
    for secret in (
        "PROMPT_SECRET",
        "ENV_SECRET",
        "TOKEN_SECRET",
        "TOOL_SECRET",
        "RAW_SECRET",
        "FULL_RESULT_SECRET",
        "OUTSIDE_SECRET",
    ):
        assert secret not in serialized

    cross_root = store.get_dashboard_messages(root_handle="root-handle", agent_handle="other-agent")
    invalid = store.get_dashboard_messages(root_handle="root/invalid", agent_handle="agent-handle")
    assert cross_root["messages"] == []
    assert invalid["messages"] == []
