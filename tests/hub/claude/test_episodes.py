"""Tests for the ``episodes`` liveness object (open/close bracketing)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from basecamp.hub.claude.store import SessionStore


def _session(store: SessionStore, session_id: str = "session-1") -> str:
    store.upsert_session(session_id=session_id, cwd=f"/tmp/{session_id}")
    return session_id


def _open_episode_rows(db_path: Path, session_id: str) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM episodes WHERE session_id = ? AND ended_at IS NULL",
            (session_id,),
        ).fetchall()


def test_open_episode_makes_the_session_live_and_returns_an_id(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    session_id = _session(store)

    episode_id = store.open_episode(session_id=session_id, source="startup")

    assert episode_id
    assert [row["session_id"] for row in store.list_open_sessions()] == [session_id]
    rows = _open_episode_rows(db_path, session_id)
    assert len(rows) == 1
    assert rows[0]["source"] == "startup"
    assert rows[0]["started_at"]


def test_close_episode_ends_liveness_and_records_reason(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    session_id = _session(store)
    store.open_episode(session_id=session_id, source="startup")

    closed = store.close_episode(session_id=session_id, reason="logout")

    assert closed is True
    assert store.list_open_sessions() == []
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT ended_at, end_reason FROM episodes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    assert row["ended_at"]
    assert row["end_reason"] == "logout"


def test_close_episode_on_unknown_session_returns_false(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    assert store.close_episode(session_id="ghost") is False


def test_close_episode_twice_returns_false_the_second_time(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    session_id = _session(store)
    store.open_episode(session_id=session_id)

    assert store.close_episode(session_id=session_id) is True
    assert store.close_episode(session_id=session_id) is False


def test_reopen_after_close_is_live_again_under_a_new_episode(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    session_id = _session(store)
    first = store.open_episode(session_id=session_id, source="startup")
    store.close_episode(session_id=session_id, reason="clear")

    second = store.open_episode(session_id=session_id, source="clear")

    assert second != first
    assert [row["session_id"] for row in store.list_open_sessions()] == [session_id]
    # Exactly one episode is live; the first is closed, the second open.
    assert len(_open_episode_rows(db_path, session_id)) == 1
    with sqlite3.connect(db_path) as connection:
        total = connection.execute("SELECT COUNT(*) FROM episodes WHERE session_id = ?", (session_id,)).fetchone()[0]
    assert total == 2


def test_current_episode_id_tracks_the_open_episode(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    session_id = _session(store)

    assert store.current_episode_id(session_id=session_id) is None  # no episode yet

    opened = store.open_episode(session_id=session_id, source="startup")
    assert store.current_episode_id(session_id=session_id) == opened

    store.close_episode(session_id=session_id, reason="logout")
    assert store.current_episode_id(session_id=session_id) is None  # closed → none live


def test_open_episode_defensively_closes_a_dangling_prior_episode(tmp_path: Path) -> None:
    # A SessionStart with no paired SessionEnd (e.g. compact, or a crashed prior
    # process) must never leave two live episodes for one session.
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    session_id = _session(store)
    first = store.open_episode(session_id=session_id, source="startup")
    second = store.open_episode(session_id=session_id, source="compact")

    live = _open_episode_rows(db_path, session_id)
    assert len(live) == 1
    assert live[0]["id"] == second
    # The dangling first episode was closed, but with no end_reason (unpaired).
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        first_row = connection.execute("SELECT ended_at, end_reason FROM episodes WHERE id = ?", (first,)).fetchone()
    assert first_row["ended_at"]
    assert first_row["end_reason"] is None
