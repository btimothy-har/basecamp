"""Tests for session-liveness store methods (``ended_at`` marker)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.hub.store import Store


def _register(store: Store, agent_id: str, **overrides: object) -> None:
    kwargs: dict[str, object] = {
        "agent_id": agent_id,
        "parent_id": None,
        "sibling_group": None,
        "depth": 0,
        "role": "agent",
        "session_name": agent_id,
        "cwd": f"/tmp/{agent_id}",
    }
    kwargs.update(overrides)
    store.upsert_agent(**kwargs)


def test_new_agent_starts_open(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    _register(store, "session-1")

    assert [row["id"] for row in store.list_open_sessions()] == ["session-1"]


def test_mark_agent_ended_closes_session(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    _register(store, "session-1")

    ended = store.mark_agent_ended("session-1")

    assert ended is True
    assert store.list_open_sessions() == []


def test_mark_agent_ended_returns_false_for_unknown_id(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")

    assert store.mark_agent_ended("nope") is False


def test_re_register_reopens_ended_session(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    _register(store, "session-1")
    store.mark_agent_ended("session-1")

    _register(store, "session-1", session_name="resumed")

    open_ids = [row["id"] for row in store.list_open_sessions()]
    assert open_ids == ["session-1"]
    with sqlite3.connect(tmp_path / "daemon.db") as connection:
        ended_at = connection.execute("SELECT ended_at FROM agents WHERE id = 'session-1'").fetchone()[0]
    assert ended_at is None


def test_list_open_sessions_excludes_ended_and_orders_by_last_seen(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = Store(db_path=db_path)
    _register(store, "old")
    _register(store, "mid")
    _register(store, "new")
    _register(store, "gone")
    store.mark_agent_ended("gone")

    # Force deterministic, distinct last_seen ordering rather than racing _now().
    with sqlite3.connect(db_path) as connection:
        for agent_id, seen in [
            ("old", "2026-01-01T00:00:00+00:00"),
            ("mid", "2026-01-02T00:00:00+00:00"),
            ("new", "2026-01-03T00:00:00+00:00"),
        ]:
            connection.execute("UPDATE agents SET last_seen_at = ? WHERE id = ?", (seen, agent_id))

    open_ids = [row["id"] for row in store.list_open_sessions()]
    assert open_ids == ["new", "mid", "old"]


def test_list_open_sessions_excludes_workers(tmp_path: Path) -> None:
    # Dispatched swarm workers (role='worker') share the agents table but are never
    # ended via a SessionEnd hook, so list_open_sessions must not report them.
    store = Store(db_path=tmp_path / "daemon.db")
    _register(store, "session-1", role="agent")
    _register(store, "worker-1", role="worker", depth=1, parent_id="session-1")

    open_ids = [row["id"] for row in store.list_open_sessions()]
    assert open_ids == ["session-1"]


def test_pre_migration_rows_are_backfilled_as_ended(tmp_path: Path) -> None:
    # A realistic pre-ended_at database (schema already past the role remap, i.e.
    # user_version=1, but with no ended_at column). Its rows predate the hook
    # lifecycle, so opening the store must backfill them as ended rather than
    # report them as open forever.
    db_path = tmp_path / "daemon.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE agents (
                id TEXT PRIMARY KEY, parent_id TEXT, depth INTEGER, role TEXT,
                session_name TEXT, cwd TEXT, created_at TEXT, last_seen_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO agents (id, role, depth, created_at, last_seen_at)
            VALUES ('stale', 'agent', 0, NULL, '2020-01-01T00:00:00+00:00')
            """
        )
        connection.execute("PRAGMA user_version = 1")
        connection.commit()

    store = Store(db_path=db_path)

    assert store.list_open_sessions() == []


def test_list_open_sessions_projects_identity_facets(tmp_path: Path) -> None:
    store = Store(db_path=tmp_path / "daemon.db")
    _register(
        store,
        "session-1",
        role="agent",
        session_file="/transcripts/session-1.jsonl",
        repo="acme/widgets",
        worktree_label="copilot/brave-otter-quill",
    )

    rows = store.list_open_sessions()

    assert len(rows) == 1
    row = rows[0]
    assert row["repo"] == "acme/widgets"
    assert row["worktree_label"] == "copilot/brave-otter-quill"
    assert row["session_file"] == "/transcripts/session-1.jsonl"
    assert row["role"] == "agent"
    assert row["parent_id"] is None
    assert set(row) == {
        "id",
        "role",
        "depth",
        "parent_id",
        "session_name",
        "cwd",
        "session_file",
        "repo",
        "worktree_label",
        "created_at",
        "last_seen_at",
    }
