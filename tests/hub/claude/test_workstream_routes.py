"""Claude daemon workstream HTTP route tests (create / list / get / status / attach)."""

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
    assert body["live"] == 0  # no attached live session yet; no stored status


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


def test_list_filters(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c", repo="acme/web"))
        client.post("/workstreams", json=_create_body(id="ws_2", slug="d-e-f", repo="acme/api"))
        all_rows = client.get("/workstreams").json()["workstreams"]
        assert {w["id"] for w in all_rows} == {"ws_1", "ws_2"}
        web = client.get("/workstreams", params={"repo": "acme/web"}).json()["workstreams"]
        assert {w["id"] for w in web} == {"ws_1"}
        # both are idle (no attached live session) -> the prune audit lists both
        idle = client.get("/workstreams", params={"idle": "true"}).json()["workstreams"]
        assert {w["id"] for w in idle} == {"ws_1", "ws_2"}
        assert client.get("/workstreams", params={"idle": "false"}).json()["workstreams"] == []


def test_get_reports_derived_live(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c"))
        # a workstream with no attached live session is not live
        assert client.get("/workstreams/ws_1").json()["live"] == 0


def test_attach_and_list_sessions(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c"))
        att = client.post(
            "/workstreams/a-b-c/attach",
            json={"session_id": "s1", "repo": "acme/web", "worktree_path": "/wt/1"},
        )
        assert att.status_code == 200 and att.json()["attached"] is True
        client.post("/workstreams/ws_1/attach", json={"session_id": "s2", "repo": "acme/api"})
        sessions = client.get("/workstreams/ws_1/sessions").json()["sessions"]
        assert {s["session_id"] for s in sessions} == {"s1", "s2"}
        # attaching to an unknown workstream -> 404
        assert client.post("/workstreams/nope/attach", json={"session_id": "s3"}).status_code == 404
        # sessions of an unknown workstream -> 404
        assert client.get("/workstreams/nope/sessions").status_code == 404


def test_delete_workstream(tmp_path: Path) -> None:
    client = _build(tmp_path)
    with client:
        client.post("/workstreams", json=_create_body(id="ws_1", slug="a-b-c"))
        client.post("/workstreams/ws_1/attach", json={"session_id": "s1"})
        assert client.delete("/workstreams/ws_1").status_code == 200
        assert client.get("/workstreams/ws_1").status_code == 404
        assert client.delete("/workstreams/ws_1").status_code == 404
