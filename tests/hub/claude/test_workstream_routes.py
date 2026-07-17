"""Claude daemon workstream HTTP route tests (create / list / get / by-worktree / status)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from basecamp.hub.claude.app import create_claude_app
from basecamp.hub.claude.store import SessionStore


def _build(tmp_path: Path) -> TestClient:
    store = SessionStore(db_path=tmp_path / "daemon.db")
    return TestClient(create_claude_app(store))


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"id": "ws_1", "slug": "brave-otter-fox"}
    body.update(overrides)
    return body


def test_create_returns_201_and_record(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        resp = client.post("/workstreams", json=_create_body(label="auth", repo="acme/web"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == "ws_1"
    assert body["slug"] == "brave-otter-fox"
    assert body["status"] == "open"


def test_duplicate_slug_returns_409(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        assert client.post("/workstreams", json=_create_body(id="ws_1", slug="dup")).status_code == 201
        resp = client.post("/workstreams", json=_create_body(id="ws_2", slug="dup"))
    assert resp.status_code == 409


def test_get_by_id_and_slug_and_404(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c"))
        assert client.get("/workstreams/ws_1").status_code == 200
        assert client.get("/workstreams/a-b-c").json()["id"] == "ws_1"
        assert client.get("/workstreams/missing").status_code == 404


def test_by_worktree_lookup_and_404(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c", worktree_path="/wt/a-b-c"))
        hit = client.get("/workstreams/by-worktree", params={"path": "/wt/a-b-c"})
        assert hit.status_code == 200
        assert hit.json()["id"] == "ws_1"
        miss = client.get("/workstreams/by-worktree", params={"path": "/wt/nope"})
        assert miss.status_code == 404


def test_list_filters(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c", repo="acme/web"))
        client.post("/workstreams", json=_create_body(id="ws_2", slug="d-e-f", repo="acme/api"))
        all_rows = client.get("/workstreams").json()["workstreams"]
        assert {w["id"] for w in all_rows} == {"ws_1", "ws_2"}
        web = client.get("/workstreams", params={"repo": "acme/web"}).json()["workstreams"]
        assert {w["id"] for w in web} == {"ws_1"}


def test_status_roundtrip_and_validation(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c"))
        ok = client.post("/workstreams/ws_1/status", json={"status": "closed"})
        assert ok.status_code == 200 and ok.json()["updated"] is True
        assert client.get("/workstreams/ws_1").json()["status"] == "closed"
        # invalid status -> 400
        assert client.post("/workstreams/ws_1/status", json={"status": "archived"}).status_code == 400
        # unknown workstream -> 404
        assert client.post("/workstreams/nope/status", json={"status": "open"}).status_code == 404
