"""Tests for daemon SQLite store initialization and agent upsert."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from basecamp.daemon.store import ActiveRunExistsError, Store


def test_store_initializes_required_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    Store(db_path=db_path)

    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()

    table_names = {row[0] for row in rows}
    assert "agents" in table_names
    assert "runs" in table_names
    assert "run_events" in table_names


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
            "run_id": "run-owned",
            "status": "running",
            "result": None,
            "error": None,
        }
    ]

    unauthorized = store.get_agents_current_runs(["agent-1"], dispatcher_id="dispatcher-2")
    assert unauthorized == [
        {
            "agent_id": "agent-1",
            "run_id": None,
            "status": None,
            "result": None,
            "error": None,
        }
    ]

    missing = store.get_agents_current_runs(["agent-missing"], dispatcher_id="dispatcher-1")
    assert missing == []


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

    assert store.set_run_result_if_unset(
        run_id="run-failed",
        status="failed",
        result="oops",
        error="agent failed",
    ) is True

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
        "runs": [],
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
    assert {run["run_id"] for run in result["runs"]} == {
        "run-root",
        "run-child",
        "run-grandchild",
        "run-child-pending",
    }


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
    assert [run["run_id"] for run in result["runs"]] == ["run-child", "run-root"]


def test_get_run_summary_orders_runs_descending_and_respects_limit(tmp_path: Path) -> None:
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

    _insert_run(db_path=db_path, run_id="run-old", agent_id="root", status="running", created_at="2026-01-01T00:00:00Z")
    _insert_run(db_path=db_path, run_id="run-mid", agent_id="root", status="running", created_at="2026-01-02T00:00:00Z")
    _insert_run(db_path=db_path, run_id="run-new", agent_id="root", status="running", created_at="2026-01-03T00:00:00Z")

    limited = store.get_run_summary("root", limit=2)
    assert [row["run_id"] for row in limited["runs"]] == ["run-new", "run-mid"]

    neg_limit = store.get_run_summary("root", limit=-5)
    assert neg_limit["runs"] == []
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
    _insert_run(
        db_path=db_path,
        run_id="run-sensitive",
        agent_id="root",
        status="completed",
        created_at="2026-01-01T00:00:00Z",
        spec_json='{"env": {"OPENAI_API_KEY": "secret"}}',
        report_token_hash="super-secret-token-hash",
        result="line one\nline two",
        error="x" * 200,
    )

    result = store.get_run_summary("root")

    assert len(result["runs"]) == 1
    summary_run = result["runs"][0]
    assert set(summary_run) == {
        "run_id",
        "agent_id",
        "parent_id",
        "role",
        "session_name",
        "status",
        "result_preview",
        "error_preview",
        "exit_code",
        "created_at",
        "started_at",
        "ended_at",
    }
    assert "spec_json" not in summary_run
    assert "report_token_hash" not in summary_run
    assert "result" not in summary_run
    assert "error" not in summary_run
    assert summary_run["result_preview"] == "line one line two"
    assert summary_run["error_preview"].endswith("…")
    assert len(summary_run["error_preview"]) == 160


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
