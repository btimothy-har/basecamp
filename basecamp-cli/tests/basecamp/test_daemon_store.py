"""Tests for daemon SQLite store initialization and agent upsert."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.daemon.store import Store


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

    store.create_run(run_id="run-1", agent_id="agent-1", spec={"task": "x"})
    seq = store.append_run_event(run_id="run-1", kind="turn_end", payload={"turnIndex": 1})
    assert seq == 1

    events = store.get_run_events("run-1")
    assert len(events) == 1
    assert events[0]["kind"] == "turn_end"
    assert events[0]["payload_json"] == {"turnIndex": 1}
