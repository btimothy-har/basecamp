import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pi_memory.constants import SERVICE_NAME, SERVICE_VERSION
from pi_memory.db import Database
from pi_memory.ingest import TranscriptIngestService
from pi_memory.server import create_app


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def observe_client(tmp_path) -> Iterator[TestClient]:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    app = create_app(
        memory_dir=tmp_path / "memory",
        ingest_service=TranscriptIngestService(database=database),
    )
    try:
        yield TestClient(app)
    finally:
        database.close_if_open()


def session_line(entry_id: str = "session-1") -> bytes:
    return f'{{"type":"session","id":"{entry_id}"}}\n'.encode()


def message_line(
    entry_id: str,
    parent_id: str | None = None,
    role: str = "user",
) -> bytes:
    parent = "" if parent_id is None else f',"parentId":"{parent_id}"'
    return (f'{{"type":"message","id":"{entry_id}"{parent},"message":{{"role":"{role}"}}}}\n').encode()


def observe_payload(path: Path, session_id: str = "pi-session-1") -> dict[str, object]:
    return {"session_id": session_id, "transcript_path": str(path)}


def test_health_endpoint(tmp_path) -> None:
    app = create_app(memory_dir=tmp_path)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_app_does_not_create_memory_database_for_status_only(tmp_path) -> None:
    memory_dir = tmp_path / "memory"

    create_app(memory_dir=memory_dir)

    assert not (memory_dir / "memory.db").exists()


def test_status_endpoint_includes_service_metadata(tmp_path) -> None:
    started_at = datetime(2026, 1, 1, tzinfo=UTC)
    app = create_app(
        host="127.0.0.1",
        port=9876,
        memory_dir=tmp_path,
        started_at=started_at,
    )
    client = TestClient(app)

    response = client.get("/v1/status")

    assert response.status_code == 200
    data = response.json()
    assert data["service_name"] == SERVICE_NAME
    assert data["version"] == SERVICE_VERSION
    assert data["pid"] == os.getpid()
    assert data["started_at"] == started_at.isoformat()
    assert data["uptime_seconds"] >= 0
    assert data["host"] == "127.0.0.1"
    assert data["port"] == 9876
    assert data["memory_dir"] == str(tmp_path)


def test_observe_endpoint_ingests_transcript_and_returns_diagnostics(
    tmp_path,
    observe_client: TestClient,
) -> None:
    path = tmp_path / "transcript.jsonl"
    content = session_line() + message_line(
        "message-1",
        parent_id="session-1",
        role="assistant",
    )
    path.write_bytes(content)

    response = observe_client.post(
        "/v1/observe",
        json={
            **observe_payload(path),
            "cwd": "/workspace/basecamp",
            "repo_name": "basecamp",
            "repo_root": "/workspace/basecamp",
            "worktree_label": "task-branch",
            "worktree_path": "/worktrees/task-branch",
            "request_id": "request-1",
            "request_metadata": {"trigger": "test"},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "session_id",
        "transcript_id",
        "entries_ingested",
        "cursor_offset",
        "file_size",
        "observed_at",
        "malformed_lines",
        "unsupported_lines",
    }
    assert data["session_id"] == "pi-session-1"
    assert isinstance(data["transcript_id"], int)
    assert data["entries_ingested"] == 2
    assert data["cursor_offset"] == len(content)
    assert data["file_size"] == len(content)
    assert datetime.fromisoformat(data["observed_at"])
    assert data["malformed_lines"] == 0
    assert data["unsupported_lines"] == 0


def test_observe_endpoint_repeated_request_ingests_zero_entries(
    tmp_path,
    observe_client: TestClient,
) -> None:
    path = tmp_path / "transcript.jsonl"
    content = session_line() + message_line("message-1")
    path.write_bytes(content)

    first_response = observe_client.post("/v1/observe", json=observe_payload(path))
    second_response = observe_client.post("/v1/observe", json=observe_payload(path))

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["entries_ingested"] == 2
    assert second_response.json()["entries_ingested"] == 0
    assert second_response.json()["cursor_offset"] == len(content)


def test_observe_endpoint_ingests_only_appended_entry(
    tmp_path,
    observe_client: TestClient,
) -> None:
    path = tmp_path / "transcript.jsonl"
    initial_content = session_line()
    appended_line = message_line("message-1")
    path.write_bytes(initial_content)

    first_response = observe_client.post("/v1/observe", json=observe_payload(path))
    path.write_bytes(initial_content + appended_line)
    second_response = observe_client.post("/v1/observe", json=observe_payload(path))

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["entries_ingested"] == 1
    assert second_response.json()["entries_ingested"] == 1
    assert second_response.json()["cursor_offset"] == len(initial_content) + len(appended_line)


def test_observe_endpoint_missing_transcript_returns_404(
    tmp_path,
    observe_client: TestClient,
) -> None:
    missing_path = tmp_path / "missing.jsonl"

    response = observe_client.post("/v1/observe", json=observe_payload(missing_path))

    assert response.status_code == 404
    assert "Transcript file does not exist" in response.json()["detail"]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"transcript_path": "/tmp/transcript.jsonl"},
        {"session_id": "pi-session-1"},
        {"session_id": "", "transcript_path": "/tmp/transcript.jsonl"},
        {"session_id": "   ", "transcript_path": "/tmp/transcript.jsonl"},
        {"session_id": "pi-session-1", "transcript_path": ""},
        {"session_id": "pi-session-1", "transcript_path": "   "},
        {
            "session_id": "pi-session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "cwd": "",
        },
        {
            "session_id": "pi-session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "request_metadata": "bad",
        },
        {
            "session_id": "pi-session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "unexpected": "field",
        },
    ],
)
def test_observe_endpoint_invalid_payload_returns_422(
    observe_client: TestClient,
    payload: dict[str, object],
) -> None:
    response = observe_client.post("/v1/observe", json=payload)

    assert response.status_code == 422
