"""Tests for daemon SQLite store initialization and agent upsert."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from pi_swarm.store import ActiveRunExistsError, DuplicateAgentHandleError, Store


def test_store_initializes_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

    table_names = {row[0] for row in rows}
    assert "agents" in table_names
    assert "runs" in table_names
    assert "run_events" in table_names


def test_store_migrates_agent_handle_column_and_backfills_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                current_run_id TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agents (id, parent_id, sibling_group, depth, role, session_name, cwd, created_at, last_seen_at)
            VALUES ('legacy-id', NULL, NULL, 0, 'session', 'legacy', '/tmp', 'created', 'seen')
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()}
        row = connection.execute("SELECT agent_handle FROM agents WHERE id = 'legacy-id'").fetchone()
        indexes = connection.execute("PRAGMA index_list(agents)").fetchall()

    assert "agent_handle" in columns
    assert row == ("legacy-id",)
    assert any(index[1] == "idx_agents_agent_handle_unique" and index[2] for index in indexes)


def test_store_migrates_agent_model_column(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY,
                parent_id TEXT,
                sibling_group TEXT,
                depth INTEGER,
                role TEXT,
                session_name TEXT,
                cwd TEXT,
                created_at TEXT,
                last_seen_at TEXT,
                current_run_id TEXT,
                agent_handle TEXT,
                agent_type TEXT,
                run_kind TEXT
            )
            """
        )

    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(agents)").fetchall()}

    assert "model" in columns


def test_upsert_agent_persists_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group="sg",
        depth=2,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, parent_id, depth, session_name, cwd
            FROM agents
            WHERE id = 'agent-1'
            """
        ).fetchall()

    assert len(rows) == 1
    assert rows[0] == ("agent-1", "parent-1", 2, "session-b", "/tmp/b")


def test_upsert_agent_persists_gets_and_preserves_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="readable",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
        model="claude-sonnet-4-5",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    agent = store.get_agent("agent-1")
    by_handle = store.get_agent_by_handle("readable")
    assert agent is not None
    assert agent["agent_handle"] == "readable"
    assert agent["model"] == "claude-sonnet-4-5"
    assert by_handle is not None
    assert by_handle["id"] == "agent-1"


def test_upsert_agent_rejects_duplicate_handle(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="shared",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )

    with pytest.raises(DuplicateAgentHandleError):
        store.upsert_agent(
            agent_id="agent-2",
            agent_handle="shared",
            parent_id=None,
            sibling_group="sg",
            depth=1,
            role="agent",
            session_name="session-b",
            cwd="/tmp/b",
        )


def test_upsert_agent_rejects_fallback_handle_collision(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        agent_handle="agent-2",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )

    with pytest.raises(DuplicateAgentHandleError):
        store.upsert_agent(
            agent_id="agent-2",
            parent_id=None,
            sibling_group="sg",
            depth=1,
            role="agent",
            session_name="session-b",
            cwd="/tmp/b",
        )


def test_run_event_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    seq = store.append_run_event(run_id="run-1", kind="turn_end", payload={"turnIndex": 1})
    assert seq == 1

    run = store.get_run("run-1")
    assert run is not None
    assert run["report_token_hash"] == "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

    events = store.get_run_events("run-1")
    assert len(events) == 1
    assert events[0]["kind"] == "turn_end"
    assert events[0]["payload_json"] == {"turnIndex": 1}


def test_create_run_stores_dispatcher_and_updates_current_run(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-dispatch",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    run = store.get_run("run-dispatch")
    assert run is not None
    assert run["dispatcher_id"] == "dispatcher-1"

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-dispatch"


def test_get_agents_current_runs_filters_by_dispatcher(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
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


def test_resolve_agent_root_follows_parents_defensively(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        session_name="agent-a1",
        cwd="/tmp/a1",
    )
    store.upsert_agent(
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=1,
        role="agent",
        session_name="lost",
        cwd="/tmp/lost",
    )

    assert store.resolve_agent_root("agent-1") == "root"
    assert store.resolve_agent_root("root") == "root"
    assert store.resolve_agent_root("lost") == "lost"
    assert store.resolve_agent_root("missing") is None


def test_get_root_agent_directory_scopes_to_root_and_excludes_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        role="session",
        session_name="outside-session",
        cwd="/tmp/out",
    )
    store.upsert_agent(
        agent_id="outside-agent",
        parent_id="outside-root",
        sibling_group="sg-oa",
        depth=1,
        role="agent",
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
    assert rows[0]["role"] == "agent"
    assert rows[1]["role"] == "worker"
    assert rows[0]["awaitable"] is False
    assert rows[1]["awaitable"] is False
    assert all(row["agent_id"] != "outside-agent" for row in rows)


def test_get_root_agent_directory_filters_awaitable_agents_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        role="agent",
        session_name="cycle-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="cycle-b",
        parent_id="cycle-a",
        sibling_group="sg-b",
        depth=2,
        role="agent",
        session_name="cycle-b",
        cwd="/tmp/b",
    )
    rows = store.get_root_agent_directory(requester_node_id="cycle-a", awaitable=False)
    assert {row["agent_id"] for row in rows} == {"cycle-a", "cycle-b"}
    assert all(row["role"] != "session" for row in rows)

    store.upsert_agent(
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=3,
        role="agent",
        session_name="lost",
        cwd="/tmp/c",
    )

    rows = store.get_root_agent_directory(requester_node_id="lost", awaitable=False)
    assert [row["agent_id"] for row in rows] == ["lost"]


def test_create_run_rejects_non_terminal_duplicate_for_agent(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-first",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    with pytest.raises(ActiveRunExistsError):
        store.create_run(
            run_id="run-second",
            agent_id="agent-1",
            dispatcher_id="dispatcher-1",
            spec={"task": "x"},
            report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT COUNT(*) AS total FROM runs WHERE agent_id = ?",
            ("agent-1",),
        ).fetchone()
    assert rows is not None
    assert rows[0] == 1


def test_set_run_result_preserves_agent_current_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-complete",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    store.set_run_result(
        run_id="run-complete",
        status="completed",
        result="done",
        error=None,
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-complete"


def test_set_run_result_if_unset_preserves_agent_current_run_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id=None,
        sibling_group="sg",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.create_run(
        run_id="run-failed",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    assert (
        store.set_run_result_if_unset(
            run_id="run-failed",
            status="failed",
            result="oops",
            error="agent failed",
        )
        is True
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["current_run_id"] == "run-failed"


def test_get_run_wait_results_includes_nonterminal_and_omits_unknown(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-running",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )
    rows = store.get_run_wait_results(["run-running", "run-missing"])
    assert rows == [{"run_id": "run-running", "status": "running", "result": None, "error": None}]

    rows_terminal = store.get_run_wait_results(["run-running", "run-missing"], terminal_only=True)
    assert rows_terminal == []

    store.set_run_result(
        run_id="run-running",
        status="completed",
        result="done",
        error=None,
    )
    rows = store.get_run_wait_results(["run-running", "run-missing"])
    assert rows == [{"run_id": "run-running", "status": "completed", "result": "done", "error": None}]


def test_get_run_summary_unknown_root_returns_empty_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    result = store.get_run_summary("does-not-exist")

    assert result == {
        "root_id": "does-not-exist",
        "counts": {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
            "total": 0,
        },
        "agents": [],
    }


def test_get_run_summary_scope_and_counts_include_descendants(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="child",
        sibling_group="sg-grandchild",
        depth=2,
        role="worker",
        session_name="grandchild-agent",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="outside",
        parent_id=None,
        sibling_group="sg-outside",
        depth=0,
        role="session",
        session_name="outside-session",
        cwd="/tmp/outside",
    )

    _insert_run(
        db_path=db_path,
        run_id="run-root",
        agent_id="root",
        status="running",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:01Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-grandchild",
        agent_id="grandchild",
        status="failed",
        created_at="2026-01-01T00:00:02Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child-pending",
        agent_id="child",
        status="pending",
        created_at="2026-01-01T00:00:03Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-outside",
        agent_id="outside",
        status="failed",
        created_at="2026-01-01T00:00:04Z",
    )

    result = store.get_run_summary("root")

    assert result["root_id"] == "root"
    assert result["counts"] == {
        "pending": 1,
        "running": 1,
        "completed": 1,
        "failed": 1,
        "total": 4,
    }
    agents = {agent["agent_handle"]: agent for agent in result["agents"]}
    assert set(agents) == {"child", "grandchild"}
    assert agents["child"]["status"] == "pending"
    assert agents["grandchild"]["status"] == "failed"


def test_get_run_summary_handles_cyclic_agent_relationships(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="root",
        parent_id="child",
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )

    _insert_run(
        db_path=db_path,
        run_id="run-root",
        agent_id="root",
        status="running",
        created_at="2026-01-01T00:00:00Z",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-child",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:01Z",
    )

    result = store.get_run_summary("root")

    assert result["counts"] == {
        "pending": 0,
        "running": 1,
        "completed": 1,
        "failed": 0,
        "total": 2,
    }
    assert [agent["agent_handle"] for agent in result["agents"]] == ["child"]
    assert result["agents"][0]["status"] == "completed"


def test_get_run_summary_orders_agents_descending_and_respects_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group="sg-root",
        depth=0,
        role="session",
        session_name="root-session",
        cwd="/tmp/root",
    )
    for agent_id, created_at in [
        ("agent-old", "2026-01-01T00:00:00Z"),
        ("agent-mid", "2026-01-02T00:00:00Z"),
        ("agent-new", "2026-01-03T00:00:00Z"),
    ]:
        store.upsert_agent(
            agent_id=agent_id,
            parent_id="root",
            sibling_group=f"sg-{agent_id}",
            depth=1,
            role="agent",
            session_name=agent_id,
            cwd=f"/tmp/{agent_id}",
        )
        _insert_run(
            db_path=db_path,
            run_id=f"run-{agent_id}",
            agent_id=agent_id,
            status="running",
            created_at=created_at,
        )

    limited = store.get_run_summary("root", limit=2)
    assert [row["agent_handle"] for row in limited["agents"]] == ["agent-new", "agent-mid"]

    neg_limit = store.get_run_summary("root", limit=-5)
    assert neg_limit["agents"] == []
    assert neg_limit["counts"] == {
        "pending": 0,
        "running": 3,
        "completed": 0,
        "failed": 0,
        "total": 3,
    }


def test_get_run_summary_does_not_expose_spec_or_tokens(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

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
        agent_id="child",
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )
    _insert_run(
        db_path=db_path,
        run_id="run-sensitive",
        agent_id="child",
        status="completed",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="super-secret-token-hash",
        result="line one\nline two",
        error="x" * 200,
    )

    result = store.get_run_summary("root")

    assert len(result["agents"]) == 1
    summary_agent = result["agents"][0]
    assert set(summary_agent) == {
        "agent_handle",
        "agent_id_short",
        "agent_type",
        "model",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
        "task",
        "recent_activity",
    }
    assert summary_agent["agent_id_short"] == "child"
    assert summary_agent["model"] == "default"
    assert "run_id" not in summary_agent
    assert "agent_id" not in summary_agent
    assert "spec_json" not in summary_agent
    assert "report_token_hash" not in summary_agent
    assert "result" not in summary_agent
    assert "error" not in summary_agent
    assert summary_agent["result_preview"] == "line one line two"
    assert summary_agent["error_preview"].endswith("…")
    assert len(summary_agent["error_preview"]) == 160
    assert summary_agent["task"] is None
    assert summary_agent["recent_activity"] == []


def test_get_run_summary_projects_safe_task_log_and_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)

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
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
        model="claude-haiku-4-5",
    )
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={"env": {"SECRET": "nope"}, "cwd": "/secret"},
        report_token_hash="secret-token-hash",
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_execution_start",
        payload={
            "toolName": "read\x1b[31m",
            "turnIndex": 2,
            "timestamp": "agent-supplied-timestamp",
            "args": {"path": "/secret"},
            "output": "private",
            "toolCallId": "call-secret",
            "cwd": "/secret",
            "env": {"TOKEN": "secret"},
            "error": "private",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_call",
        payload={
            "category": "tool",
            "label": "Read file",
            "snippet": "opening /safe/path",
            "toolName": "read",
            "toolCallId": "call-secret",
            "raw": {"args": "private"},
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="tool_result",
        payload={
            "category": "tool",
            "label": "Read file",
            "snippet": "done",
            "toolName": "read",
            "isError": False,
            "toolCallId": "call-secret",
            "output": "private output",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="assistant_output",
        payload={
            "category": "assistant",
            "snippet": "safe answer",
            "text": "full safe answer",
            "message": "raw message",
        },
    )
    store.append_run_event(
        run_id="run-1",
        kind="thinking",
        payload={"category": "thinking", "snippet": "thinking…", "chainOfThought": "hidden"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="agent_result",
        payload={"category": "result", "label": "Completed", "snippet": "summary", "isError": True},
    )
    store.append_run_event(
        run_id="run-1",
        kind="turn_end",
        payload={"turnIndex": 3, "toolCount": 2, "raw": "private"},
    )
    store.append_run_event(
        run_id="run-1",
        kind="raw_model_delta",
        payload={"toolName": "should-not-leak", "turnIndex": 4},
    )
    with sqlite3.connect(db_path) as connection:
        for seq in range(1, 9):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:0{seq - 1}Z", "run-1", seq),
            )
    _write_task_log(
        task_dir,
        "agent-1",
        [
            {
                "goal": "Ship \x1b[32mobservability\x1b[0m\x07",
                "active": True,
                "tasks": [
                    {"label": "Done", "description": "d", "criteria": "c", "notes": None, "status": "completed"},
                    {"label": 456, "description": "bad", "criteria": "bad", "notes": None, "status": "completed"},
                    {"label": 123, "description": "bad", "criteria": "bad", "notes": None, "status": "pending"},
                    {
                        "label": "Bad status",
                        "description": "bad",
                        "criteria": "bad",
                        "notes": None,
                        "status": "unknown",
                    },
                    "not-a-task",
                    {
                        "label": "Current\x1b]0;title\x07 task",
                        "description": "Desc\x00 with controls",
                        "criteria": "c",
                        "notes": "n" * 400,
                        "status": "active",
                    },
                    {"label": "Deleted", "description": "d", "criteria": "c", "notes": None, "status": "deleted"},
                    {"label": "Pending", "description": "d", "criteria": "c", "notes": None, "status": "pending"},
                ],
            }
        ],
    )

    result = store.get_run_summary("root")

    agent = result["agents"][0]
    assert "agent_id" not in agent
    assert "run_id" not in agent
    assert agent["agent_id_short"] == "agent1"
    assert agent["model"] == "claude-haiku-4-5"
    assert agent["task"] == {
        "goal": "Ship observability",
        "progress": {"completed": 1, "deleted": 1, "total": 3},
        "task_plan": [
            {"index": 0, "label": "Done", "status": "completed"},
            {"index": 5, "label": "Current task", "status": "active"},
            {"index": 7, "label": "Pending", "status": "pending"},
        ],
        "current_task": {
            "index": 5,
            "label": "Current task",
            "status": "active",
            "description": "Desc with controls",
            "notes": f"{'n' * 239}…",
        },
    }
    assert agent["recent_activity"] == [
        {
            "kind": "tool_execution_start",
            "seq": 1,
            "timestamp": "2026-01-01T00:00:00Z",
            "toolName": "read",
            "turnIndex": 2,
        },
        {
            "kind": "tool_call",
            "seq": 2,
            "timestamp": "2026-01-01T00:00:01Z",
            "category": "tool",
            "label": "Read file",
            "snippet": "opening /safe/path",
            "toolName": "read",
        },
        {
            "kind": "tool_result",
            "seq": 3,
            "timestamp": "2026-01-01T00:00:02Z",
            "category": "tool",
            "label": "Read file",
            "snippet": "done",
            "toolName": "read",
            "isError": False,
        },
        {
            "kind": "assistant_output",
            "seq": 4,
            "timestamp": "2026-01-01T00:00:03Z",
            "category": "assistant",
            "snippet": "safe answer",
        },
        {
            "kind": "thinking",
            "seq": 5,
            "timestamp": "2026-01-01T00:00:04Z",
            "category": "thinking",
            "snippet": "thinking…",
        },
        {
            "kind": "agent_result",
            "seq": 6,
            "timestamp": "2026-01-01T00:00:05Z",
            "category": "result",
            "label": "Completed",
            "snippet": "summary",
            "isError": True,
        },
        {
            "kind": "turn_end",
            "seq": 7,
            "timestamp": "2026-01-01T00:00:06Z",
            "turnIndex": 3,
            "toolCount": 2,
        },
    ]
    assert agent["recent_activity"][0]["timestamp"] != "agent-supplied-timestamp"
    assert all(activity["kind"] != "raw_model_delta" for activity in agent["recent_activity"])
    for activity in agent["recent_activity"]:
        assert all(
            key not in activity
            for key in [
                "args",
                "output",
                "toolCallId",
                "cwd",
                "env",
                "error",
                "payload",
                "raw",
                "message",
                "text",
                "chainOfThought",
            ]
        )


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


def test_get_run_summary_bounds_and_tolerates_malformed_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _summary_agent(store)
    store.create_run(
        run_id="run-1",
        agent_id="agent-1",
        dispatcher_id="root",
        spec={},
        report_token_hash="hash",
    )

    for index in range(12):
        store.append_run_event(
            run_id="run-1",
            kind="tool_call",
            payload={"snippet": f"event {index + 1}", "isError": "bad" if index == 4 else False},
        )

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE run_events SET payload_json = ? WHERE run_id = ? AND seq = ?",
            ("{not-json", "run-1", 4),
        )
        for seq in range(1, 13):
            connection.execute(
                "UPDATE run_events SET ts = ? WHERE run_id = ? AND seq = ?",
                (f"2026-01-01T00:00:{seq:02d}Z", "run-1", seq),
            )

    activity = store.get_run_summary("root")["agents"][0]["recent_activity"]

    assert len(activity) == 10
    assert [item["seq"] for item in activity] == list(range(3, 13))
    malformed = activity[1]
    assert malformed == {
        "kind": "tool_call",
        "seq": 4,
        "timestamp": "2026-01-01T00:00:04Z",
    }
    non_bool_error = activity[2]
    assert non_bool_error["seq"] == 5
    assert non_bool_error["snippet"] == "event 5"
    assert "isError" not in non_bool_error


def test_get_run_summary_tolerates_malformed_task_logs(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)
    _summary_agent(store)
    task_dir.mkdir()
    (task_dir / "agent-1.json").write_text("not json", encoding="utf-8")

    result = store.get_run_summary("root")

    assert result["agents"][0]["task"] is None


def test_get_run_summary_rejects_unsafe_task_log_paths_symlinks_and_size(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    task_dir = tmp_path / "tasks"
    store = Store(db_path=db_path, task_dir=task_dir)
    _summary_agent(store, agent_id="../escape")
    task_dir.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps([{"goal": "bad", "active": True, "tasks": []}]), encoding="utf-8")
    (task_dir / "..%2Fescape.json").write_text("[]", encoding="utf-8")

    assert store.get_run_summary("root")["agents"][0]["task"] is None

    store = Store(db_path=tmp_path / "daemon2.db", task_dir=task_dir)
    _summary_agent(store, agent_id="agent-1")
    (task_dir / "agent-1.json").symlink_to(outside)
    assert store.get_run_summary("root")["agents"][0]["task"] is None

    (task_dir / "agent-1.json").unlink()
    (task_dir / "agent-1.json").write_text("[" + (" " * (256 * 1024)) + "]", encoding="utf-8")
    assert store.get_run_summary("root")["agents"][0]["task"] is None


def _summary_agent(store: Store, *, agent_id: str = "agent-1") -> None:
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
        agent_id=agent_id,
        parent_id="root",
        sibling_group="sg-child",
        depth=1,
        role="agent",
        session_name="child-agent",
        cwd="/tmp/child",
    )


def _write_task_log(task_dir: Path, agent_id: str, cycles: list[dict[str, object]]) -> None:
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / f"{agent_id}.json").write_text(json.dumps(cycles), encoding="utf-8")


def _insert_run(
    *,
    db_path: Path,
    run_id: str,
    agent_id: str,
    status: str,
    created_at: str,
    spec_json: str = "{}",
    report_token_hash: str | None = None,
    result: str | None = None,
    error: str | None = None,
    exit_code: int | None = None,
) -> None:
    started_at = created_at
    ended_at = created_at if status in {"completed", "failed"} else None

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO runs (
                id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_id,
                status,
                spec_json,
                report_token_hash,
                result,
                error,
                exit_code,
                created_at,
                started_at,
                ended_at,
            ),
        )
        connection.execute(
            "UPDATE agents SET current_run_id = ? WHERE id = ?",
            (run_id, agent_id),
        )
