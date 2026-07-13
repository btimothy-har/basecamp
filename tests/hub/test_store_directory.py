"""Tests for daemon store agent directory and current-run projections."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.hub.store import Store


def test_get_agents_current_runs_filters_by_dispatcher(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="worker",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-owned",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    owned = store.get_agents_current_runs(["agent-1"], dispatcher_id="dispatcher-1")
    assert owned == [
        {
            "agent_id": "agent-1",
            "agent_handle": "agent-1",
            "run_id": "run-owned",
            "status": "running",
            "result": None,
            "error": None,
        }
    ]

    owned_by_handle = store.get_agents_current_runs_by_handles(["agent-1"], dispatcher_id="dispatcher-1")
    assert owned_by_handle == owned

    unauthorized = store.get_agents_current_runs(["agent-1"], dispatcher_id="dispatcher-2")
    assert unauthorized == [
        {
            "agent_id": "agent-1",
            "agent_handle": "agent-1",
            "run_id": None,
            "status": None,
            "result": None,
            "error": None,
        }
    ]

    missing = store.get_agents_current_runs(["agent-missing"], dispatcher_id="dispatcher-1")
    assert missing == []


def test_get_agents_current_runs_excludes_sessions_from_wait_projection(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        agent_handle="root-handle",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.create_run(
        run_id="run-session",
        agent_id="root",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    assert store.get_agents_current_runs(["root"], dispatcher_id="root") == []
    assert store.get_agents_current_runs_by_handles(["root-handle"], dispatcher_id="root") == []


def test_get_root_agent_directory_scopes_to_root_and_excludes_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="worker",
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="worker",
        session_name="worker-a2",
        cwd="/tmp/a2",
    )
    store.upsert_agent(
        agent_id="outside-root",
        parent_id=None,
        sibling_group="sg-out",
        depth=0,
        role="agent",
        session_name="outside-session",
        cwd="/tmp/out",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-oa",
        depth=1,
        role="worker",
        session_name="outside-agent",
        cwd="/tmp/out-agent",
    )

    store.create_run(
        run_id="run-a1",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-a2",
        agent_id="agent-2",
        dispatcher_id="dispatcher-2",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-a2",
        status="completed",
        result="done",
        error=None,
    )

    rows = store.get_root_agent_directory(requester_node_id="agent-2", awaitable=False)
    assert [row["agent_id"] for row in rows] == ["agent-1", "agent-2"]
    assert [row["agent_handle"] for row in rows] == ["agent-1", "agent-2"]
    assert rows[0]["parent_id"] == "root"
    assert rows[1]["parent_id"] == "agent-1"
    assert rows[0]["status"] == "running"
    assert rows[1]["status"] == "completed"
    assert rows[0]["role"] == "worker"
    assert rows[1]["role"] == "worker"
    assert rows[0]["awaitable"] is False
    assert rows[1]["awaitable"] is False
    assert all(row["agent_id"] != "outside-agent" for row in rows)


def test_get_root_agent_directory_includes_sanitized_current_task_and_stable_agent_type(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="worker",
        session_name="swift-panda-5604f5",
        cwd="/tmp/a1",
        agent_handle="swift-panda-5604f5",
        agent_type="scout",
    )
    store.create_run(
        run_id="run-old",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "Initial task", "env": {"SECRET": "do-not-leak"}},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-old",
        status="completed",
        result="done",
        error=None,
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="worker",
        session_name="swift-panda-5604f5",
        cwd="/tmp/a1-retask",
    )
    store.create_run(
        run_id="run-current",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "Retask \x1b[31mfunctional\x1b[0m\ncheck\x00", "env": {"SECRET": "do-not-leak"}},
        report_token_hash="hash",
    )

    rows = store.get_root_agent_directory(requester_node_id="root", awaitable=False)

    assert len(rows) == 1
    assert rows[0]["agent_handle"] == "swift-panda-5604f5"
    assert rows[0]["agent_type"] == "scout"
    assert rows[0]["task"] == "Retask functional check"
    assert "SECRET" not in rows[0]
    assert "spec_json" not in rows[0]


def test_get_root_agent_directory_excludes_ask_agents_but_run_summary_includes_them(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="normal-agent",
        parent_id="root",
        sibling_group="sg-normal",
        depth=1,
        role="worker",
        session_name="normal-agent",
        cwd="/tmp/normal",
    )
    store.upsert_agent(
        agent_id="ask-agent",
        parent_id="root",
        sibling_group="sg-ask",
        depth=1,
        role="worker",
        session_name="ask-agent",
        cwd="/tmp/ask",
        agent_type="ask",
    )
    store.create_run(
        run_id="run-normal",
        agent_id="normal-agent",
        dispatcher_id="root",
        spec={"task": "normal"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-ask",
        agent_id="ask-agent",
        dispatcher_id="root",
        spec={"task": "ask"},
        report_token_hash="hash",
    )

    directory_rows = store.get_root_agent_directory(requester_node_id="root", awaitable=False)
    summary = store.get_run_summary("root")

    assert [row["agent_id"] for row in directory_rows] == ["normal-agent"]
    assert {agent["agent_handle"] for agent in summary["agents"]} == {"normal-agent", "ask-agent"}
    assert summary["counts"]["total"] == 2


def test_get_root_agent_directory_filters_awaitable_agents_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="agent",
        session_name="root-session",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="root",
        sibling_group="sg-a1",
        depth=1,
        role="worker",
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="agent-2",
        parent_id="agent-1",
        sibling_group="sg-a2",
        depth=2,
        role="worker",
        session_name="worker-a2",
        cwd="/tmp/a2",
    )

    store.create_run(
        run_id="run-a1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.create_run(
        run_id="run-a2",
        agent_id="agent-2",
        dispatcher_id="agent-1",
        spec={"task": "x"},
        report_token_hash="hash",
    )
    store.set_run_result(
        run_id="run-a2",
        status="completed",
        result="done",
        error=None,
    )

    rows = store.get_root_agent_directory(requester_node_id="agent-1", awaitable=True)
    assert [row["agent_id"] for row in rows] == ["agent-2"]
    assert rows[0]["status"] == "completed"
    assert rows[0]["awaitable"] is True


def test_get_root_agent_directory_handles_cycle_and_missing_parent_defensively(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="cycle-a",
        parent_id="cycle-b",
        sibling_group="sg-a",
        depth=1,
        role="worker",
        session_name="cycle-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="cycle-b",
        parent_id="cycle-a",
        sibling_group="sg-b",
        depth=2,
        role="worker",
        session_name="cycle-b",
        cwd="/tmp/b",
    )
    rows = store.get_root_agent_directory(requester_node_id="cycle-a", awaitable=False)
    assert {row["agent_id"] for row in rows} == {"cycle-a", "cycle-b"}
    assert all(row["role"] != "agent" for row in rows)

    store.upsert_agent(
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=3,
        role="worker",
        session_name="lost",
        cwd="/tmp/c",
    )

    rows = store.get_root_agent_directory(requester_node_id="lost", awaitable=False)
    assert [row["agent_id"] for row in rows] == ["lost"]


def test_get_root_agent_directory_soft_expires_stale_disconnected_agents(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    for agent_id, parent in (("supervisor", None), ("fresh-child", "supervisor"), ("stale-child", "supervisor")):
        store.upsert_agent(
            agent_id=agent_id,
            parent_id=parent,
            sibling_group="supervisor",
            depth=0 if parent is None else 1,
            role="worker",
            session_name=agent_id,
            cwd="/tmp",
            agent_handle=f"{agent_id}-handle",
        )

    # Age stale-child's last-seen well beyond the 24h soft-expiry TTL.
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE agents SET last_seen_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", "stale-child"),
        )

    visible = {row["agent_id"] for row in store.get_root_agent_directory(requester_node_id="supervisor")}
    assert "fresh-child" in visible
    assert "stale-child" not in visible

    # A live connection exempts an otherwise-expired row from the roster.
    with_live = {
        row["agent_id"]
        for row in store.get_root_agent_directory(requester_node_id="supervisor", live_node_ids={"stale-child"})
    }
    assert "stale-child" in with_live
