"""Tests for daemon store run message projections."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from store_helpers import _summary_agent

from basecamp.swarm.store import Store


def test_get_run_messages_projects_selected_agent_latest_three_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"env": {"SECRET": "nope"}},
        report_token_hash="hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "one", "text": "one"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_result",
        payload={"text": "tool output should not appear"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "two", "text": "two"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "three", "text": "\x1b[31mthree\x1b[0m\nline\x00"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "four", "text": "four"},
    )
    store.set_run_result(run_id="run-1", status="completed", result="final\nanswer", error=None)

    with sqlite3.connect(db_path) as connection:
        for seq in range(1, 6):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:0{seq}Z", "run-1", seq),
            )
        connection.execute(
            "UPDATE runs SET ended_at = ? WHERE id = ?",
            ("2026-01-01T00:00:06Z", "run-1"),
        )

    result = store.get_run_messages("root", agent_handle="agent-1")

    assert result == {
        "root_id": "root",
        "agent_handle": "agent-1",
        "messages": [
            {
                "kind": "assistant_output",
                "seq": 4,
                "timestamp": "2026-01-01T00:00:04Z",
                "label": "assistant",
                "text": "three\nline",
            },
            {
                "kind": "assistant_output",
                "seq": 5,
                "timestamp": "2026-01-01T00:00:05Z",
                "label": "assistant",
                "text": "four",
            },
            {
                "kind": "agent_result",
                "seq": None,
                "timestamp": "2026-01-01T00:00:06Z",
                "label": "result",
                "text": "final\nanswer",
            },
        ],
    }
    for message in result["messages"]:
        assert set(message) == {"kind", "seq", "timestamp", "label", "text"}


def test_get_run_messages_deduplicates_terminal_result_and_validates_scope(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(run_id="run-1", agent_id="agent-1", dispatcher_id="root", spec={}, report_token_hash="hash")
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "same", "text": "same"},
    )
    store.set_run_result(run_id="run-1", status="completed", result="same", error=None)
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-outside",
        depth=0,
        role="session",
        session_name="outside-root",
        cwd="/tmp/outside",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-outside-child",
        depth=1,
        role="agent",
        session_name="outside-agent",
        cwd="/tmp/outside-agent",
    )
    store.create_run(
        run_id="run-outside",
        agent_id="outside-agent",
        dispatcher_id="outside-root",
        spec={},
        report_token_hash="hash",
    )
    store.append_run_event(
        run_id="run-outside",
        kind="assistant_output",
        payload={"label": "assistant", "snippet": "private", "text": "private outside text"},
    )

    scoped = store.get_run_messages("root", agent_handle="agent-1")
    outside = store.get_run_messages("root", agent_handle="outside-agent")

    assert [message["text"] for message in scoped["messages"]] == ["same"]
    assert outside == {"root_id": "root", "agent_handle": "outside-agent", "messages": []}
