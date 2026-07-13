"""Tests for daemon store run lifecycle, run events, and wait results."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basecamp.hub.store import ActiveRunExistsError, Store


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
        role="worker",
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


def test_set_run_pgid_persists_and_get_run_returns_value(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(
        run_id="run-pgid",
        agent_id="agent-1",
        dispatcher_id="dispatcher-1",
        spec={"task": "x"},
        report_token_hash="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
    )

    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] is None

    store.set_run_pgid(run_id="run-pgid", pgid=4321)
    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] == 4321

    store.set_run_pgid(run_id="run-pgid", pgid=None)
    run = store.get_run("run-pgid")
    assert run is not None
    assert run["pgid"] is None


def test_get_nonterminal_runs_returns_pending_and_running_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.create_run(run_id="run-completed", agent_id="agent-completed", dispatcher_id="root", spec={})
    store.set_run_result(run_id="run-completed", status="completed", result="done", error=None)
    store.create_run(run_id="run-failed", agent_id="agent-failed", dispatcher_id="root", spec={})
    store.set_run_result(run_id="run-failed", status="failed", result=None, error="failed")
    store.create_run(run_id="run-running", agent_id="agent-running", dispatcher_id="root", spec={})
    store.set_run_pgid(run_id="run-running", pgid=4321)

    rows = store.get_nonterminal_runs()

    assert rows == [{"id": "run-running", "agent_id": "agent-running", "pgid": 4321, "status": "running"}]


def test_resolve_agent_root_follows_parents_defensively(tmp_path: Path) -> None:
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
        agent_id="lost",
        parent_id="missing-parent",
        sibling_group="sg-lost",
        depth=1,
        role="worker",
        session_name="lost",
        cwd="/tmp/lost",
    )

    assert store.resolve_agent_root("agent-1") == "root"
    assert store.resolve_agent_root("root") == "root"
    assert store.resolve_agent_root("lost") == "lost"
    assert store.resolve_agent_root("missing") is None


def test_create_run_rejects_non_terminal_duplicate_for_agent(tmp_path: Path) -> None:
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
        role="worker",
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
        role="worker",
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
