"""Claude daemon HTTP route tests (health / register / end / ingest / list)."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from basecamp.hub.claude.app import create_claude_app
from basecamp.hub.claude.contract import CLAUDE_PROTOCOL_VERSION
from basecamp.hub.claude.routes import register_claude_routes
from basecamp.hub.claude.store import SessionStore


def _build(tmp_path: Path) -> tuple[TestClient, SessionStore, Path]:
    db_path = tmp_path / "daemon.db"
    store = SessionStore(db_path=db_path)
    return TestClient(create_claude_app(store)), store, db_path


def _build_with_recorder(tmp_path: Path) -> tuple[TestClient, SessionStore, list[dict[str, Any]]]:
    """Build a client whose ingest scheduling is a recorder, not a real background task."""

    store = SessionStore(db_path=tmp_path / "daemon.db")
    calls: list[dict[str, Any]] = []
    app = FastAPI()
    register_claude_routes(app, store=store, schedule_ingest=lambda **kwargs: calls.append(kwargs))
    return TestClient(app), store, calls


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


def test_ingest_schedules_with_stored_path_and_live_episode(tmp_path: Path) -> None:
    client, store, calls = _build_with_recorder(tmp_path)

    with client:
        client.post(
            "/sessions",
            json=_register_body("session-1", source="startup", transcript_path="/transcripts/s1.jsonl"),
        )
        response = client.post("/sessions/session-1/ingest", json={"reason": "session-end"})

    assert response.status_code == 200
    assert response.json() == {"session_id": "session-1", "scheduled": True}
    assert calls == [
        {
            "session_id": "session-1",
            "transcript_path": "/transcripts/s1.jsonl",
            "episode_id": store.current_episode_id(session_id="session-1"),
            "sweep_sidecars": False,
            "agent_transcript_path": None,
        }
    ]


def test_ingest_session_end_requests_a_sidecar_sweep(tmp_path: Path) -> None:
    client, _store, calls = _build_with_recorder(tmp_path)

    with client:
        client.post("/sessions", json=_register_body("session-1", transcript_path="/stored.jsonl"))
        response = client.post("/sessions/session-1/ingest", json={"reason": "session-end", "sweep_sidecars": True})

    assert response.json()["scheduled"] is True
    assert calls[0]["sweep_sidecars"] is True
    assert calls[0]["agent_transcript_path"] is None


def test_ingest_subagent_stop_targets_the_sidecar_without_a_stored_path(tmp_path: Path) -> None:
    # SubagentStop targets its own sidecar, so it schedules even for an unregistered
    # session (no stored main path) as long as agent_transcript_path is present.
    client, _store, calls = _build_with_recorder(tmp_path)

    with client:
        response = client.post(
            "/sessions/ghost/ingest",
            json={"reason": "subagent-stop", "agent_transcript_path": "/subagents/agent-x.jsonl"},
        )

    assert response.json() == {"session_id": "ghost", "scheduled": True}
    assert calls[0]["agent_transcript_path"] == "/subagents/agent-x.jsonl"
    assert calls[0]["transcript_path"] is None


def test_ingest_body_path_overrides_stored_path(tmp_path: Path) -> None:
    client, _store, calls = _build_with_recorder(tmp_path)

    with client:
        client.post("/sessions", json=_register_body("session-1", transcript_path="/stored.jsonl"))
        response = client.post("/sessions/session-1/ingest", json={"transcript_path": "/override.jsonl"})

    assert response.json()["scheduled"] is True
    assert calls[0]["transcript_path"] == "/override.jsonl"


def test_ingest_returns_not_scheduled_when_the_store_is_busy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A contended lock that outlasts busy_timeout raises OperationalError on the reads;
    # the route degrades to an explicit not-scheduled reply, never an unhandled 500.
    client, store, calls = _build_with_recorder(tmp_path)

    def _boom(**_kwargs: object) -> object:
        msg = "database is locked"
        raise sqlite3.OperationalError(msg)

    with client:
        client.post("/sessions", json=_register_body("session-1", transcript_path="/stored.jsonl"))
        monkeypatch.setattr(store, "current_episode_id", _boom)
        response = client.post("/sessions/session-1/ingest", json={"reason": "session-end", "sweep_sidecars": True})

    assert response.status_code == 200
    assert response.json() == {"session_id": "session-1", "scheduled": False, "reason": "store busy"}
    assert calls == []


def test_ingest_without_a_known_path_is_not_scheduled(tmp_path: Path) -> None:
    client, _store, calls = _build_with_recorder(tmp_path)

    with client:
        response = client.post("/sessions/ghost/ingest", json={})

    assert response.status_code == 200
    assert response.json() == {"session_id": "ghost", "scheduled": False, "reason": "no transcript path"}
    assert calls == []


def test_ingest_default_scheduler_stores_nodes_end_to_end(tmp_path: Path) -> None:
    # Exercises the real (non-injected) IngestScheduler wired by create_claude_app.
    transcript = tmp_path / "t.jsonl"
    transcript.write_text('{"uuid":"a","type":"user"}\n{"uuid":"b","parentUuid":"a","type":"assistant"}\n')
    client, store, _db = _build(tmp_path)

    with client:
        client.post("/sessions", json=_register_body("session-1", transcript_path=str(transcript)))
        response = client.post("/sessions/session-1/ingest", json={"reason": "pre-compact"})
        assert response.json()["scheduled"] is True
        for _ in range(100):
            if store.count_transcript_nodes("session-1") >= 2:
                break
            time.sleep(0.02)

    assert store.count_transcript_nodes("session-1") == 2


def test_app_drains_ingest_scheduler_on_shutdown(tmp_path: Path) -> None:
    # The last-chance SessionEnd ingest runs as a detached task; app shutdown must
    # await it rather than let the process exit mid-parse.
    store = SessionStore(db_path=tmp_path / "daemon.db")
    app = create_claude_app(store)

    class _FakeScheduler:
        def __init__(self) -> None:
            self.drained = False

        async def drain(self) -> None:
            self.drained = True

    fake = _FakeScheduler()
    app.state.ingest_scheduler = fake

    with TestClient(app):  # entering/exiting runs the lifespan startup + shutdown
        pass

    assert fake.drained is True
