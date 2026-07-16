"""Claude daemon HTTP route tests (health / register / end / list)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from basecamp.hub.claude.app import create_claude_app
from basecamp.hub.claude.contract import CLAUDE_PROTOCOL_VERSION
from basecamp.hub.claude.store import SessionStore


def _build(tmp_path: Path) -> tuple[TestClient, SessionStore, Path]:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    return TestClient(create_claude_app(store)), store, db_path


def _register_body(session_id: str, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"session_id": session_id, "cwd": f"/tmp/{session_id}"}
    body.update(overrides)
    return body


def test_health_reports_protocol(tmp_path: Path) -> None:
    client, _store, _db = _build(tmp_path)

    with client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "protocol": CLAUDE_PROTOCOL_VERSION}


def test_register_then_end_round_trip(tmp_path: Path) -> None:
    client, _store, _db = _build(tmp_path)

    with client:
        registered = client.post("/sessions", json=_register_body("session-1", source="startup"))
        assert registered.status_code == 200
        assert registered.json() == {
            "session_id": "session-1",
            "protocol": CLAUDE_PROTOCOL_VERSION,
            "status": "registered",
        }

        listed = client.get("/sessions")
        assert listed.status_code == 200
        assert [row["session_id"] for row in listed.json()["sessions"]] == ["session-1"]

        ended = client.post("/sessions/session-1/end", json={"reason": "logout"})
        assert ended.status_code == 200
        assert ended.json() == {"session_id": "session-1", "ended": True}

        after = client.get("/sessions")
        assert after.json()["sessions"] == []


def test_register_persists_identity_and_opens_an_episode(tmp_path: Path) -> None:
    client, store, _db = _build(tmp_path)

    with client:
        response = client.post(
            "/sessions",
            json=_register_body(
                "session-1",
                source="resume",
                transcript_path="/transcripts/s1.jsonl",
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
    assert row["episode_source"] == "resume"


def test_end_records_reason_on_the_episode(tmp_path: Path) -> None:
    client, _store, db_path = _build(tmp_path)

    with client:
        client.post("/sessions", json=_register_body("session-1", source="startup"))
        client.post("/sessions/session-1/end", json={"reason": "logout"})

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT source, end_reason FROM episodes WHERE session_id = 'session-1'").fetchone()
    assert row["source"] == "startup"
    assert row["end_reason"] == "logout"


def test_register_rejects_missing_required_fields(tmp_path: Path) -> None:
    # The Claude-owned body — not a frame ``type``/``v`` gate — is what validates now.
    client, _store, _db = _build(tmp_path)

    with client:
        no_session = client.post("/sessions", json={"cwd": "/tmp/x"})
        no_cwd = client.post("/sessions", json={"session_id": "s1"})

    assert no_session.status_code == 422
    assert no_cwd.status_code == 422


def test_end_unknown_session_reports_not_ended(tmp_path: Path) -> None:
    client, _store, _db = _build(tmp_path)

    with client:
        response = client.post("/sessions/ghost/end", json={})

    assert response.status_code == 200
    assert response.json() == {"session_id": "ghost", "ended": False}
