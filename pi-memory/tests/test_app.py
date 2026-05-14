import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pi_memory.constants import SERVICE_NAME, SERVICE_VERSION
from pi_memory.db import JOB_KIND_PROCESS_TRANSCRIPT, Database, Job, MemorySession, Transcript, TranscriptEntry
from pi_memory.ingest import TranscriptIngestService
from pi_memory.jobs import JobStore
from pi_memory.server import create_app


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def observe_client(tmp_path) -> Iterator[TestClient]:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    app = create_app(
        memory_dir=tmp_path / "memory",
        ingest_service=TranscriptIngestService(database=database),
        job_store=JobStore(database=database),
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
    content: str | None = None,
) -> bytes:
    parent = "" if parent_id is None else f',"parentId":"{parent_id}"'
    message_content = "" if content is None else f',"content":"{content}"'
    return (
        f'{{"type":"message","id":"{entry_id}"{parent},"message":{{"role":"{role}"{message_content}}}}}\n'
    ).encode()


def observe_payload(path: Path, session_id: str = "pi-session-1") -> dict[str, object]:
    return {"session_id": session_id, "transcript_path": str(path)}


def observe_jobs(client: TestClient) -> list[Job]:
    return client.app.state.job_store.list_jobs(kind=JOB_KIND_PROCESS_TRANSCRIPT)


def assert_observe_job_payload(
    job: Job,
    data: dict[str, object],
    *,
    forbidden_text: str | None = None,
) -> None:
    assert job.kind == JOB_KIND_PROCESS_TRANSCRIPT
    assert job.payload_json["transcript_id"] == data["transcript_id"]
    assert job.payload_json["session_id"] == data["session_id"]
    assert job.payload_json["observation_id"] == data["observation_id"]
    assert job.payload_json["entries_ingested"] == data["entries_ingested"]
    assert job.payload_json["cursor_offset"] == data["cursor_offset"]
    assert job.payload_json["file_size"] == data["file_size"]
    assert job.payload_json["malformed_lines"] == data["malformed_lines"]
    assert job.payload_json["unsupported_lines"] == data["unsupported_lines"]
    assert datetime.fromisoformat(job.payload_json["observed_at"]) == datetime.fromisoformat(
        data["observed_at"],
    )
    assert "raw_line" not in job.payload_json
    if forbidden_text is not None:
        assert forbidden_text not in str(job.payload_json)


class FakeDispatcher:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_lifespan_starts_and_stops_dispatcher(tmp_path) -> None:
    dispatcher = FakeDispatcher()
    app = create_app(memory_dir=tmp_path, dispatcher=dispatcher)

    assert app.state.dispatcher is dispatcher
    with TestClient(app) as client:
        assert dispatcher.started is True
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    assert dispatcher.stopped is True


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
        content="do not enqueue raw",
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
        "observation_id",
        "entries_ingested",
        "cursor_offset",
        "file_size",
        "observed_at",
        "malformed_lines",
        "unsupported_lines",
        "job_id",
    }
    assert data["session_id"] == "pi-session-1"
    assert isinstance(data["transcript_id"], int)
    assert isinstance(data["observation_id"], int)
    assert isinstance(data["job_id"], int)
    assert data["entries_ingested"] == 2
    assert data["cursor_offset"] == len(content)
    assert data["file_size"] == len(content)
    assert datetime.fromisoformat(data["observed_at"])
    assert data["malformed_lines"] == 0
    assert data["unsupported_lines"] == 0
    jobs = observe_jobs(observe_client)
    assert len(jobs) == 1
    assert jobs[0].id == data["job_id"]
    assert_observe_job_payload(jobs[0], data, forbidden_text="do not enqueue raw")


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
    first_data = first_response.json()
    second_data = second_response.json()
    assert first_data["entries_ingested"] == 2
    assert isinstance(first_data["job_id"], int)
    assert second_data["entries_ingested"] == 0
    assert second_data["job_id"] is None
    assert second_data["cursor_offset"] == len(content)
    jobs = observe_jobs(observe_client)
    assert len(jobs) == 1
    assert jobs[0].id == first_data["job_id"]


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
    first_data = first_response.json()
    second_data = second_response.json()
    assert first_data["entries_ingested"] == 1
    assert second_data["entries_ingested"] == 1
    assert isinstance(first_data["job_id"], int)
    assert isinstance(second_data["job_id"], int)
    assert second_data["cursor_offset"] == len(initial_content) + len(appended_line)
    jobs = observe_jobs(observe_client)
    assert len(jobs) == 2
    assert {job.id for job in jobs} == {first_data["job_id"], second_data["job_id"]}
    for job in jobs:
        data = first_data if job.id == first_data["job_id"] else second_data
        assert_observe_job_payload(job, data)


def test_observe_endpoint_missing_transcript_returns_404(
    tmp_path,
    observe_client: TestClient,
) -> None:
    missing_path = tmp_path / "missing.jsonl"

    response = observe_client.post("/v1/observe", json=observe_payload(missing_path))

    assert response.status_code == 404
    assert "Transcript file does not exist" in response.json()["detail"]


def test_get_job_endpoint_returns_serialized_job_without_transcript_content(tmp_path) -> None:
    database = Database(sqlite_url(tmp_path / "memory-jobs.db"))
    app = create_app(memory_dir=tmp_path / "memory", job_store=JobStore(database=database))
    now = datetime(2026, 1, 1, 10, tzinfo=UTC)
    try:
        job = app.state.job_store.enqueue(
            JOB_KIND_PROCESS_TRANSCRIPT,
            payload_json={"transcript_id": 1, "session_id": "pi-session-1"},
            due_at=now,
            now=now,
        )
        with database.session() as db_session:
            memory_session = MemorySession(session_id="pi-session-1")
            transcript = Transcript(
                session=memory_session,
                path="/tmp/pi/transcript.jsonl",
                cursor_offset=10,
                file_size=10,
            )
            db_session.add(transcript)
            db_session.flush()
            db_session.add(
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id="entry-1",
                    entry_type="message",
                    message_role="user",
                    raw_line='{"content":"secret transcript text"}',
                    byte_start=0,
                    byte_end=10,
                ),
            )
            stored = db_session.get_one(Job, job.id)
            stored.result_json = {"ok": True}
            stored.last_error = "previous failure"
            stored.attempts = 2
            stored.created_at = now - timedelta(minutes=1)
            stored.updated_at = now + timedelta(minutes=1)

        response = TestClient(app).get(f"/v1/jobs/{job.id}")
    finally:
        database.close_if_open()

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job.id
    assert data["kind"] == JOB_KIND_PROCESS_TRANSCRIPT
    assert data["status"] == "queued"
    assert data["payload_json"] == {"transcript_id": 1, "session_id": "pi-session-1"}
    assert data["result_json"] == {"ok": True}
    assert data["attempts"] == 2
    assert data["last_error"] == "previous failure"
    assert _parse_response_time(data["due_at"]) == now
    assert _parse_response_time(data["created_at"]) == now - timedelta(minutes=1)
    assert _parse_response_time(data["updated_at"]) == now + timedelta(minutes=1)
    assert "raw_line" not in data
    assert "content" not in data
    assert "secret transcript text" not in str(data)


def _parse_response_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def test_get_job_endpoint_returns_404_for_missing_job(tmp_path) -> None:
    database = Database(sqlite_url(tmp_path / "memory-missing-job.db"))
    app = create_app(memory_dir=tmp_path / "memory", job_store=JobStore(database=database))
    try:
        response = TestClient(app).get("/v1/jobs/999")
    finally:
        database.close_if_open()

    assert response.status_code == 404
    assert response.json()["detail"] == "Job 999 was not found"


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
