"""Tests for daemon store agent upsert and lookup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from basecamp.swarm.store import DuplicateAgentHandleError, Store


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


def test_get_subtree_agent_ids_returns_root_and_descendants_only(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="root",
        cwd="/tmp/root",
    )
    store.upsert_agent(
        agent_id="child",
        parent_id="root",
        sibling_group="root",
        depth=1,
        role="agent",
        session_name="child",
        cwd="/tmp/child",
    )
    store.upsert_agent(
        agent_id="grandchild",
        parent_id="child",
        sibling_group="child",
        depth=2,
        role="agent",
        session_name="grandchild",
        cwd="/tmp/grandchild",
    )
    store.upsert_agent(
        agent_id="sibling-root",
        parent_id=None,
        sibling_group=None,
        depth=0,
        role="session",
        session_name="sibling-root",
        cwd="/tmp/sibling-root",
    )

    assert set(store.get_subtree_agent_ids("root")) == {"root", "child", "grandchild"}


def test_upsert_agent_preserves_sibling_group_when_unset(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)

    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group="parent-1",
        depth=1,
        role="agent",
        session_name="session-a",
        cwd="/tmp/a",
    )
    store.upsert_agent(
        agent_id="agent-1",
        parent_id="parent-1",
        sibling_group=None,
        depth=1,
        role="agent",
        session_name="session-b",
        cwd="/tmp/b",
    )

    agent = store.get_agent("agent-1")
    assert agent is not None
    assert agent["sibling_group"] == "parent-1"


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
