"""Tests for the Claude ``SessionStore`` liveness store (``ended_at`` marker)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basecamp.hub.claude.store import SessionStore


def _register(store: SessionStore, session_id: str, **overrides: object) -> None:
    kwargs: dict[str, object] = {
        "session_id": session_id,
        "role": "agent",
        "session_name": session_id,
        "cwd": f"/tmp/{session_id}",
    }
    kwargs.update(overrides)
    store.upsert_session(**kwargs)


def test_new_session_starts_open(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "sessions.db")

    _register(store, "session-1")

    assert [row["session_id"] for row in store.list_open_sessions()] == ["session-1"]


def test_mark_session_ended_closes_it(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "sessions.db")
    _register(store, "session-1")

    ended = store.mark_session_ended("session-1")

    assert ended is True
    assert store.list_open_sessions() == []


def test_mark_session_ended_returns_false_for_unknown_id(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "sessions.db")

    assert store.mark_session_ended("nope") is False


def test_re_register_reopens_ended_session_and_preserves_created_at(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path=db_path)
    _register(store, "session-1")
    with sqlite3.connect(db_path) as connection:
        original_created = connection.execute(
            "SELECT created_at FROM sessions WHERE session_id = 'session-1'"
        ).fetchone()[0]
    store.mark_session_ended("session-1")

    _register(store, "session-1", session_name="resumed")

    open_ids = [row["session_id"] for row in store.list_open_sessions()]
    assert open_ids == ["session-1"]
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT ended_at, created_at, session_name FROM sessions WHERE session_id = 'session-1'"
        ).fetchone()
    assert row[0] is None  # ended_at reset on re-register
    assert row[1] == original_created  # created_at preserved
    assert row[2] == "resumed"  # facets refreshed


def test_list_open_sessions_excludes_ended_and_orders_by_last_seen(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    store = SessionStore(db_path=db_path)
    _register(store, "old")
    _register(store, "mid")
    _register(store, "new")
    _register(store, "gone")
    store.mark_session_ended("gone")

    # Force deterministic, distinct last_seen ordering rather than racing _now().
    with sqlite3.connect(db_path) as connection:
        for session_id, seen in [
            ("old", "2026-01-01T00:00:00+00:00"),
            ("mid", "2026-01-02T00:00:00+00:00"),
            ("new", "2026-01-03T00:00:00+00:00"),
        ]:
            connection.execute("UPDATE sessions SET last_seen_at = ? WHERE session_id = ?", (seen, session_id))

    open_ids = [row["session_id"] for row in store.list_open_sessions()]
    assert open_ids == ["new", "mid", "old"]


def test_list_open_sessions_projects_identity_facets(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "sessions.db")
    _register(
        store,
        "session-1",
        role="worker",
        depth=1,
        parent_id="root",
        transcript_path="/transcripts/session-1.jsonl",
        repo="acme/widgets",
        worktree_label="copilot/brave-otter-quill",
    )

    rows = store.list_open_sessions()

    assert len(rows) == 1
    row = rows[0]
    assert row["repo"] == "acme/widgets"
    assert row["worktree_label"] == "copilot/brave-otter-quill"
    assert row["transcript_path"] == "/transcripts/session-1.jsonl"
    assert row["role"] == "worker"
    assert row["parent_id"] == "root"
    assert row["depth"] == 1
    assert set(row) == {
        "session_id",
        "role",
        "depth",
        "parent_id",
        "session_name",
        "cwd",
        "transcript_path",
        "repo",
        "worktree_label",
        "created_at",
        "last_seen_at",
    }


def test_store_defaults_db_path_under_the_claude_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    store = SessionStore()

    assert store.db_path == tmp_path / ".pi" / "basecamp" / "claude" / "sessions.db"
    assert store.db_path.parent.is_dir()
