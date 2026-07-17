"""Tests for the ``workstreams`` store mixin — records + agent attachment."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from basecamp.hub.claude.store import SessionStore


def _store(tmp_path: Path) -> SessionStore:
    return SessionStore(db_path=tmp_path / "daemon.db")


def _create(store: SessionStore, *, workstream_id: str = "ws_1", slug: str = "brave-otter-fox", **kw: object) -> dict:
    return store.create_workstream(workstream_id=workstream_id, slug=slug, **kw)


def test_create_and_get_by_id_and_slug(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = _create(
        store,
        label="auth refactor",
        repo="acme/web-app",
        dossier_path="/g/pages/work__acme__web-app__brave-otter-fox.md",
    )
    assert created["id"] == "ws_1"
    assert created["slug"] == "brave-otter-fox"
    assert created["label"] == "auth refactor"
    assert created["dossier_path"] == "/g/pages/work__acme__web-app__brave-otter-fox.md"
    assert "worktree_path" not in created  # the record no longer binds a worktree
    assert "status" not in created  # no stored status — liveness is derived
    assert created["live"] == 0  # no attached live session yet
    assert store.get_workstream("ws_1") == created
    assert store.get_workstream("brave-otter-fox") == created
    assert store.get_workstream("nope") is None


def test_slug_collision_raises_integrity_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="dup-slug-here")
    with pytest.raises(sqlite3.IntegrityError):
        _create(store, workstream_id="ws_2", slug="dup-slug-here")


def test_list_filters_by_repo(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c", repo="acme/web")
    _create(store, workstream_id="ws_2", slug="d-e-f", repo="acme/api")
    _create(store, workstream_id="ws_3", slug="g-h-i", repo="acme/web")

    assert {w["id"] for w in store.list_workstreams()} == {"ws_1", "ws_2", "ws_3"}
    assert {w["id"] for w in store.list_workstreams(repo="acme/web")} == {"ws_1", "ws_3"}


def test_liveness_and_idle_audit_derive_from_episodes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_live", slug="a-b-c")
    _create(store, workstream_id="ws_idle", slug="d-e-f")

    # ws_live has an attached session with an open episode; ws_idle has none
    store.upsert_session(session_id="s1", cwd="/x")
    store.open_episode(session_id="s1")
    store.attach_workstream_session(identifier="ws_live", session_id="s1")

    assert store.get_workstream("ws_live")["live"] == 1
    assert store.get_workstream("ws_idle")["live"] == 0
    # the prune audit: only ws_idle (no live session)
    assert {w["id"] for w in store.list_idle_workstreams()} == {"ws_idle"}
    assert {w["id"] for w in store.list_workstreams(idle=False)} == {"ws_live"}

    # closing s1's episode makes ws_live idle too — the SessionEnd signal, no extra write
    store.close_episode(session_id="s1", reason="session-end")
    assert store.get_workstream("ws_live")["live"] == 0
    assert {w["id"] for w in store.list_idle_workstreams()} == {"ws_live", "ws_idle"}


def test_attach_session_is_additive_and_idempotent(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")

    # two different agents attach — multi-worker
    assert store.attach_workstream_session(identifier="a-b-c", session_id="s1", repo="acme/web", worktree_path="/wt/1")
    assert store.attach_workstream_session(identifier="ws_1", session_id="s2", repo="acme/api", worktree_path="/wt/2")
    sessions = store.list_workstream_sessions("ws_1")
    assert {s["session_id"] for s in sessions} == {"s1", "s2"}

    # re-attaching s1 refreshes its facets, does not duplicate
    store.attach_workstream_session(identifier="ws_1", session_id="s1", repo="acme/web2", worktree_path="/wt/1b")
    sessions = store.list_workstream_sessions("ws_1")
    assert len(sessions) == 2
    s1 = next(s for s in sessions if s["session_id"] == "s1")
    assert s1["repo"] == "acme/web2" and s1["worktree_path"] == "/wt/1b"

    # attaching to an unknown workstream -> False
    assert store.attach_workstream_session(identifier="nope", session_id="s3") is False


def test_list_sessions_liveness_from_episodes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")
    store.upsert_session(session_id="s1", cwd="/x")
    store.open_episode(session_id="s1")
    store.attach_workstream_session(identifier="ws_1", session_id="s1")
    store.attach_workstream_session(identifier="ws_1", session_id="s2")

    live = {s["session_id"]: bool(s["live"]) for s in store.list_workstream_sessions("ws_1")}
    assert live == {"s1": True, "s2": False}

    store.close_episode(session_id="s1", reason="session-end")
    live = {s["session_id"]: bool(s["live"]) for s in store.list_workstream_sessions("ws_1")}
    assert live == {"s1": False, "s2": False}


def test_delete_removes_record_and_attach_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")
    store.attach_workstream_session(identifier="ws_1", session_id="s1")
    assert store.delete_workstream("a-b-c") is True
    assert store.get_workstream("ws_1") is None
    assert store.list_workstream_sessions("ws_1") == []  # attach rows gone
    assert store.delete_workstream("ws_1") is False
