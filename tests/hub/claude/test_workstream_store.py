"""Tests for the ``workstreams`` store mixin — the C1a pointer record."""

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
        worktree_path="/wt/copilot/brave-otter-fox",
        dossier_path="/g/pages/work__acme__web-app__brave-otter-fox.md",
    )
    assert created["id"] == "ws_1"
    assert created["slug"] == "brave-otter-fox"
    assert created["status"] == "open"
    assert created["label"] == "auth refactor"
    # fetch by id and by slug both resolve
    assert store.get_workstream("ws_1") == created
    assert store.get_workstream("brave-otter-fox") == created
    assert store.get_workstream("nope") is None


def test_slug_collision_raises_integrity_error(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="dup-slug-here")
    with pytest.raises(sqlite3.IntegrityError):
        _create(store, workstream_id="ws_2", slug="dup-slug-here")


def test_get_by_worktree(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c", worktree_path="/wt/copilot/a-b-c")
    _create(store, workstream_id="ws_2", slug="d-e-f", worktree_path="/wt/copilot/d-e-f")
    assert store.get_workstream_by_worktree("/wt/copilot/d-e-f")["id"] == "ws_2"
    assert store.get_workstream_by_worktree("/wt/nonexistent") is None


def test_list_filters_by_repo_and_status(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c", repo="acme/web")
    _create(store, workstream_id="ws_2", slug="d-e-f", repo="acme/api")
    _create(store, workstream_id="ws_3", slug="g-h-i", repo="acme/web")
    store.set_workstream_status("ws_3", "closed")

    assert {w["id"] for w in store.list_workstreams()} == {"ws_1", "ws_2", "ws_3"}
    assert {w["id"] for w in store.list_workstreams(repo="acme/web")} == {"ws_1", "ws_3"}
    assert {w["id"] for w in store.list_workstreams(status="open")} == {"ws_1", "ws_2"}
    assert {w["id"] for w in store.list_workstreams(repo="acme/web", status="open")} == {"ws_1"}


def test_set_status_updates_and_rejects_invalid(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")
    assert store.set_workstream_status("ws_1", "closed") is True
    assert store.get_workstream("ws_1")["status"] == "closed"
    # unknown identifier -> no row changed
    assert store.set_workstream_status("nope", "open") is False
    # invalid status -> ValueError (route maps to 400)
    with pytest.raises(ValueError, match="invalid status"):
        store.set_workstream_status("ws_1", "archived")


def test_set_status_advances_updated_at(tmp_path: Path) -> None:
    store = _store(tmp_path)
    created = _create(store, workstream_id="ws_1", slug="a-b-c")
    store.set_workstream_status("ws_1", "closed")
    after = store.get_workstream("ws_1")
    assert after["created_at"] == created["created_at"]  # created_at preserved
    assert after["updated_at"] >= created["updated_at"]  # updated_at advanced


def test_delete_removes_record(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")
    assert store.delete_workstream("a-b-c") is True
    assert store.get_workstream("ws_1") is None
    assert store.delete_workstream("ws_1") is False


def test_set_worktree_persists_and_is_findable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _create(store, workstream_id="ws_1", slug="a-b-c")
    assert store.set_workstream_worktree("ws_1", "/wt/copilot/a-b-c") is True
    assert store.get_workstream("ws_1")["worktree_path"] == "/wt/copilot/a-b-c"
    assert store.get_workstream_by_worktree("/wt/copilot/a-b-c")["id"] == "ws_1"
    # unknown workstream -> no row changed
    assert store.set_workstream_worktree("nope", "/x") is False
