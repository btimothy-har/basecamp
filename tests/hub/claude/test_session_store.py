"""Tests for the durable ``sessions`` store (identity + episode-derived liveness)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basecamp.hub.claude.store import SessionStore


def _live_session(store: SessionStore, session_id: str, *, source: str | None = None, **facets: object) -> None:
    """Register a session and open an episode so ``list_open_sessions`` reports it live."""
    facets.setdefault("cwd", f"/tmp/{session_id}")
    store.upsert_session(session_id=session_id, **facets)
    store.open_episode(session_id=session_id, source=source)


def test_registered_session_with_open_episode_is_live(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")

    _live_session(store, "session-1")

    assert [row["session_id"] for row in store.list_open_sessions()] == ["session-1"]


def test_session_without_an_episode_is_not_live(tmp_path: Path) -> None:
    # Liveness is derived from episodes; a bare durable row is not "open".
    store = SessionStore(db_path=tmp_path / "daemon.db")

    store.upsert_session(session_id="session-1", cwd="/tmp/session-1")

    assert store.list_open_sessions() == []


def test_re_register_preserves_created_at_and_refreshes_facets(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    _live_session(store, "session-1", repo="acme/widgets")
    with sqlite3.connect(db_path) as connection:
        original_created = connection.execute(
            "SELECT created_at FROM sessions WHERE session_id = 'session-1'"
        ).fetchone()[0]

    # A resume or /clear re-registers the same id with (possibly) new facets.
    store.upsert_session(session_id="session-1", cwd="/work/resumed", repo="acme/gadgets")

    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT created_at, cwd, repo FROM sessions WHERE session_id = 'session-1'").fetchone()
    assert row[0] == original_created  # created_at preserved
    assert row[1] == "/work/resumed"  # facets refreshed
    assert row[2] == "acme/gadgets"


def test_list_open_sessions_excludes_sessions_whose_episode_closed(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    _live_session(store, "live")
    _live_session(store, "gone")
    store.close_episode(session_id="gone")

    assert [row["session_id"] for row in store.list_open_sessions()] == ["live"]


def test_list_open_sessions_orders_by_last_seen_desc(tmp_path: Path) -> None:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    for session_id in ("old", "mid", "new"):
        _live_session(store, session_id)

    # Force deterministic, distinct last_seen ordering rather than racing _now().
    with sqlite3.connect(db_path) as connection:
        for session_id, seen in [
            ("old", "2026-01-01T00:00:00+00:00"),
            ("mid", "2026-01-02T00:00:00+00:00"),
            ("new", "2026-01-03T00:00:00+00:00"),
        ]:
            connection.execute("UPDATE sessions SET last_seen_at = ? WHERE session_id = ?", (seen, session_id))

    assert [row["session_id"] for row in store.list_open_sessions()] == ["new", "mid", "old"]


def test_list_open_sessions_projects_identity_and_live_episode_facets(tmp_path: Path) -> None:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    _live_session(
        store,
        "session-1",
        source="resume",
        cwd="/work/dir",
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
    assert row["cwd"] == "/work/dir"
    assert row["handle"] is None
    assert row["episode_source"] == "resume"
    assert row["episode_started_at"]
    assert set(row) == {
        "session_id",
        "repo",
        "worktree_label",
        "handle",
        "cwd",
        "transcript_path",
        "created_at",
        "last_seen_at",
        "episode_source",
        "episode_started_at",
    }


def test_store_defaults_db_path_under_the_claude_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    store = SessionStore()

    assert store.db_path == tmp_path / ".pi" / "basecamp" / "claude" / "daemon.db"
    assert store.db_path.parent.is_dir()
