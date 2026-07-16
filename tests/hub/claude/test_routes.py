"""Claude daemon HTTP route tests (health / register / end / list)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from basecamp.hub.claude.app import create_claude_app
from basecamp.hub.claude.store import SessionStore
from basecamp.hub.frames import PROTOCOL_VERSION


def _build(tmp_path: Path) -> tuple[TestClient, SessionStore]:
    store = SessionStore(db_path=tmp_path / "sessions.db")
    return TestClient(create_claude_app(store)), store


def _register_body(node_id: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "type": "register",
        "v": PROTOCOL_VERSION,
        "role": "agent",
        "node_id": node_id,
        "parent_id": None,
        "sibling_group": None,
        "depth": 0,
        "session_name": node_id,
        "cwd": f"/tmp/{node_id}",
    }
    body.update(overrides)
    return body


def test_health_reports_protocol(tmp_path: Path) -> None:
    client, _store = _build(tmp_path)

    with client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": PROTOCOL_VERSION}


def test_register_then_end_round_trip(tmp_path: Path) -> None:
    client, _store = _build(tmp_path)

    with client:
        registered = client.post("/sessions", json=_register_body("session-1"))
        assert registered.status_code == 200
        assert registered.json() == {
            "node_id": "session-1",
            "protocol": PROTOCOL_VERSION,
            "status": "registered",
        }

        listed = client.get("/sessions")
        assert listed.status_code == 200
        assert [row["session_id"] for row in listed.json()["sessions"]] == ["session-1"]

        ended = client.post("/sessions/session-1/end")
        assert ended.status_code == 200
        assert ended.json() == {"node_id": "session-1", "ended": True}

        after = client.get("/sessions")
        assert after.json()["sessions"] == []


def test_register_persists_identity_facets(tmp_path: Path) -> None:
    client, store = _build(tmp_path)

    with client:
        response = client.post(
            "/sessions",
            json=_register_body(
                "session-1",
                role="worker",
                depth=1,
                parent_id="root",
                session_file="/transcripts/s1.jsonl",
                repo="acme/widgets",
                worktree_label="copilot/brave-otter-quill",
            ),
        )
    assert response.status_code == 200

    rows = store.list_open_sessions()
    assert len(rows) == 1
    row = rows[0]
    assert row["repo"] == "acme/widgets"
    assert row["worktree_label"] == "copilot/brave-otter-quill"
    assert row["transcript_path"] == "/transcripts/s1.jsonl"
    assert row["role"] == "worker"


def test_register_rejects_wrong_protocol_version(tmp_path: Path) -> None:
    client, _store = _build(tmp_path)

    with client:
        response = client.post("/sessions", json=_register_body("session-1", v=999))

    assert response.status_code == 422


def test_register_rejects_wrong_frame_type(tmp_path: Path) -> None:
    client, _store = _build(tmp_path)

    with client:
        response = client.post("/sessions", json=_register_body("session-1", type="peer_message"))

    assert response.status_code == 422


def test_end_unknown_session_reports_not_ended(tmp_path: Path) -> None:
    client, _store = _build(tmp_path)

    with client:
        response = client.post("/sessions/ghost/end")

    assert response.status_code == 200
    assert response.json() == {"node_id": "ghost", "ended": False}
