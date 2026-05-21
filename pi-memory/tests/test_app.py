import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pi_memory.constants import SERVICE_NAME, SERVICE_VERSION
from pi_memory.db import (
    JOB_KIND_PROCESS_TRANSCRIPT,
    Database,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
)
from pi_memory.ingest import TranscriptIngestService
from pi_memory.interpretation import SessionInterpretationInspectionService
from pi_memory.jobs import JobStore
from pi_memory.quality import SessionQualityReportInspectionService
from pi_memory.recall import RecallSearchService, index_transcript
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


@pytest.fixture
def recall_client(tmp_path) -> Iterator[tuple[TestClient, Database]]:
    database = Database(sqlite_url(tmp_path / "recall.db"))
    app = create_app(
        memory_dir=tmp_path / "memory",
        recall_service=RecallSearchService(database=database),
    )
    try:
        yield TestClient(app), database
    finally:
        database.close_if_open()


@pytest.fixture
def interpretation_client(tmp_path) -> Iterator[tuple[TestClient, Database]]:
    database = Database(sqlite_url(tmp_path / "interpretation.db"))
    app = create_app(
        memory_dir=tmp_path / "memory",
        interpretation_service=SessionInterpretationInspectionService(database=database),
    )
    try:
        yield TestClient(app), database
    finally:
        database.close_if_open()


@pytest.fixture
def quality_client(tmp_path) -> Iterator[tuple[TestClient, Database]]:
    database = Database(sqlite_url(tmp_path / "quality.db"))
    app = create_app(
        memory_dir=tmp_path / "memory",
        quality_service=SessionQualityReportInspectionService(database=database),
    )
    try:
        yield TestClient(app), database
    finally:
        database.close_if_open()


def session_line(entry_id: str = "session-1", *, cwd: str | None = None) -> bytes:
    payload = {"type": "session", "id": entry_id}
    if cwd is not None:
        payload["cwd"] = cwd
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def message_line(
    entry_id: str,
    parent_id: str | None = None,
    role: str = "user",
    content: str | None = None,
) -> bytes:
    parent = "" if parent_id is None else f',"parentId":"{parent_id}"'
    message_content = "" if content is None else f',"content":"{content}"'
    return (f'{{"type":"message","id":"{entry_id}"{parent},"message":{{"role":"{role}"{message_content}}}}}\n').encode()


def observe_payload(path: Path, session_id: str = "pi-session-1") -> dict[str, object]:
    return {"session_id": session_id, "transcript_path": str(path)}


def observe_jobs(client: TestClient) -> list[Job]:
    return client.app.state.job_store.list_jobs(kind=JOB_KIND_PROCESS_TRANSCRIPT)


def add_recall_transcript(
    database: Database,
    *,
    session_id: str = "pi-session-recall",
    transcript_path: str = "/tmp/pi/recall.jsonl",
    text: str = "The comet recall endpoint should find this raw transcript line.",
    should_index: bool = True,
) -> tuple[int, int]:
    database.initialize()
    with database.session() as db_session:
        memory_session = MemorySession(session_id=session_id)
        transcript = Transcript(session=memory_session, path=transcript_path, file_size=512)
        transcript.entries.append(
            TranscriptEntry(
                entry_id="recall-entry-1",
                entry_type="message",
                message_role="assistant",
                timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                raw_line=json.dumps(
                    {
                        "type": "message",
                        "message": {"role": "assistant", "content": text},
                    },
                ),
                byte_start=24,
                byte_end=124,
            ),
        )
        db_session.add(transcript)
        db_session.flush()
        transcript_id = transcript.id
        entry_id = transcript.entries[0].id
        if should_index:
            index_transcript(db_session, transcript_id)
    return transcript_id, entry_id


def add_interpretation_snapshot(database: Database) -> dict[str, object]:
    database.initialize()
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-interpret")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/secret-transcript.jsonl",
            cursor_offset=456,
            file_size=456,
        )
        transcript.entries.append(
            TranscriptEntry(
                entry_id="interpret-entry-1",
                entry_type="message",
                message_role="assistant",
                raw_line='{"content":"SECRET_RAW_TRANSCRIPT_TOOL_OUTPUT"}',
                byte_start=100,
                byte_end=200,
            ),
        )
        job = Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"safe": True})
        db_session.add_all([transcript, job])
        db_session.flush()
        snapshot = SessionInterpretationSnapshot(
            session_id=memory_session.id,
            transcript_id=transcript.id,
            analysis_run_id=None,
            job_id=job.id,
            status="completed",
            blocked_reason=None,
            analyzed_through_entry_id=transcript.entries[0].id,
            analyzed_through_byte_offset=200,
            origin_counts_json={
                "local_activity_count": 2,
                "inherited_activity_count": 1,
                "mixed_activity_count": 0,
                "unknown_activity_count": 0,
            },
            claim_source_activity_count=2,
            interpretation_json={"summary": "Safe interpretation", "open_questions": []},
            citations_json=[{"claim_id": "claim-1", "source_ref_id": "ar1:ep0:act0:entries1"}],
            model_metadata_json={"provider": "deterministic", "model": "test"},
            prompt_version="phase5b-session-interpretation-v1",
            schema_version=1,
            created_at=now,
            updated_at=now + timedelta(minutes=1),
        )
        db_session.add(snapshot)
        db_session.flush()
        return {
            "session_row_id": memory_session.id,
            "snapshot_id": snapshot.id,
            "transcript_id": transcript.id,
            "job_id": job.id,
            "entry_id": transcript.entries[0].id,
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
        }


def add_quality_report(
    database: Database,
    *,
    session_id: str = "pi-session-quality",
    quality_status: str = "healthy",
    quality_reason: str | None = None,
    derivation_status: str = "current",
    promotable: bool = True,
    cwd: str = "/repo/main",
    worktree_label: str = "main",
) -> dict[str, object]:
    database.initialize()
    now = datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC)
    with database.session() as db_session:
        memory_session = MemorySession(
            session_id=session_id,
            cwd=cwd,
            worktree_label=worktree_label,
            worktree_path=f"/repo/{worktree_label}",
        )
        transcript = Transcript(session=memory_session, path=f"/tmp/pi/{session_id}.jsonl", file_size=123)
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            status="completed",
            interpretation_json={"summary": "Safe interpretation"},
            citations_json=[],
            model_metadata_json={"provider": "test", "model": "interpret"},
            prompt_version="phase5b-test",
            schema_version=1,
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=quality_status,
            quality_reason=quality_reason,
            derivation_status=derivation_status,
            deterministic_status="passed",
            semantic_status="passed" if quality_status == "healthy" else "degraded",
            promotable=promotable,
            deterministic_findings_json=[],
            semantic_findings_json=[{"code": "semantic_degraded", "severity": "warning", "message": "Weak citation."}]
            if quality_status != "healthy"
            else [],
            claim_assessments_json=[],
            missing_high_signal_items_json=[],
            model_metadata_json={"provider": "test", "model": "quality", "mode": "deterministic"},
            assessment_metadata_json={"deterministic_check_version": 1},
            prompt_version="phase5c-test",
            schema_version=1,
            created_at=now,
            updated_at=now + timedelta(minutes=1),
        )
        db_session.add(report)
        db_session.flush()
        return {
            "session_id": session_id,
            "session_row_id": memory_session.id,
            "snapshot_id": snapshot.id,
            "quality_report_id": report.id,
            "created_at": report.created_at,
            "updated_at": report.updated_at,
        }


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


def test_get_session_interpretation_endpoint_returns_safe_snapshot(
    interpretation_client: tuple[TestClient, Database],
) -> None:
    client, database = interpretation_client
    expected = add_interpretation_snapshot(database)

    response = client.get("/v1/debug/sessions/pi-session-interpret/interpretation")

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "session_id": "pi-session-interpret",
        "session_row_id": expected["session_row_id"],
        "snapshot_id": expected["snapshot_id"],
        "transcript_id": expected["transcript_id"],
        "analysis_run_id": None,
        "job_id": expected["job_id"],
        "status": "completed",
        "blocked_reason": None,
        "analyzed_through_entry_id": expected["entry_id"],
        "analyzed_through_byte_offset": 200,
        "origin_counts": {
            "local_activity_count": 2,
            "inherited_activity_count": 1,
            "mixed_activity_count": 0,
            "unknown_activity_count": 0,
        },
        "claim_source_activity_count": 2,
        "interpretation_json": {"summary": "Safe interpretation", "open_questions": []},
        "citations_json": [{"claim_id": "claim-1", "source_ref_id": "ar1:ep0:act0:entries1"}],
        "episode_interpretation": {},
        "model_metadata": {"provider": "deterministic", "model": "test"},
        "prompt_version": "phase5b-session-interpretation-v1",
        "schema_version": 1,
        "created_at": data["created_at"],
        "updated_at": data["updated_at"],
    }
    assert _parse_response_time(data["created_at"]) == expected["created_at"]
    assert _parse_response_time(data["updated_at"]) == expected["updated_at"]
    assert "raw_line" not in data
    assert "transcript_path" not in data
    assert "/tmp/pi/secret-transcript.jsonl" not in str(data)
    assert "SECRET_RAW_TRANSCRIPT_TOOL_OUTPUT" not in str(data)


def test_get_session_interpretation_endpoint_returns_404_when_absent(
    interpretation_client: tuple[TestClient, Database],
) -> None:
    client, _database = interpretation_client

    response = client.get("/v1/debug/sessions/missing-session/interpretation")

    assert response.status_code == 404
    assert response.json()["detail"] == "Interpretation snapshot for session missing-session was not found"


def test_get_session_quality_endpoint_returns_safe_report(
    quality_client: tuple[TestClient, Database],
) -> None:
    client, database = quality_client
    expected = add_quality_report(database)

    response = client.get(f"/v1/debug/sessions/{expected['session_id']}/quality")

    assert response.status_code == 200
    data = response.json()
    assert data["session_id"] == expected["session_id"]
    assert data["session_row_id"] == expected["session_row_id"]
    assert data["snapshot_id"] == expected["snapshot_id"]
    assert data["quality_report_id"] == expected["quality_report_id"]
    assert data["quality_status"] == "healthy"
    assert data["quality_reason"] is None
    assert data["assessment_state"] == "complete"
    assert data["derivation_status"] == "current"
    assert data["is_current"] is True
    assert data["semantic_status"] == "passed"
    assert data["promotable"] is True
    assert data["finding_counts"] == {"critical": 0, "warning": 0, "info": 0}
    assert data["session_metadata"]["cwd"] == "/repo/main"
    assert "repo_name" not in data["session_metadata"]
    assert "repo_root" not in data["session_metadata"]
    assert "raw_line" not in str(data)
    assert "/tmp/pi" not in str(data)


def test_get_session_quality_endpoint_returns_404_when_absent(
    quality_client: tuple[TestClient, Database],
) -> None:
    client, _database = quality_client

    response = client.get("/v1/debug/sessions/missing-session/quality")

    assert response.status_code == 404
    assert response.json()["detail"] == "Quality report for session missing-session was not found"


def test_quality_report_list_endpoint_filters_and_paginates(
    quality_client: tuple[TestClient, Database],
) -> None:
    client, database = quality_client
    add_quality_report(database, session_id="healthy-1")
    add_quality_report(
        database,
        session_id="degraded-1",
        quality_status="degraded",
        quality_reason="semantic_degraded",
        promotable=False,
        cwd="/repo/feature",
        worktree_label="feature",
    )
    add_quality_report(
        database,
        session_id="outdated-1",
        quality_status="not_assessed",
        quality_reason="outdated_derivation",
        derivation_status="outdated",
        promotable=False,
    )

    response = client.get(
        "/v1/debug/quality/reports?quality_status=degraded&promotable=false&cwd=/repo/feature&limit=5",
    )

    assert response.status_code == 200
    data = response.json()
    assert data["pagination"] == {"total": 1, "returned": 1, "limit": 5, "offset": 0}
    assert data["query"]["quality_status"] == "degraded"
    assert data["query"]["cwd"] == "/repo/feature"
    assert data["results"][0]["session_id"] == "degraded-1"
    assert data["results"][0]["finding_counts"] == {"critical": 0, "warning": 1, "info": 0}

    current_response = client.get("/v1/debug/quality/reports?is_current=false")
    assert current_response.status_code == 200
    assert [result["session_id"] for result in current_response.json()["results"]] == ["outdated-1"]


def test_quality_report_sample_endpoint_returns_bounded_results(
    quality_client: tuple[TestClient, Database],
) -> None:
    client, database = quality_client
    for index in range(4):
        add_quality_report(database, session_id=f"sample-{index}")

    response = client.get("/v1/debug/quality/reports/sample?count=2")

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["results"]) == 2


def test_quality_report_list_invalid_filter_returns_422(
    quality_client: tuple[TestClient, Database],
) -> None:
    client, _database = quality_client

    response = client.get("/v1/debug/quality/reports?quality_status=invalid")

    assert response.status_code == 422


def test_recall_search_endpoint_returns_indexed_raw_transcript_hit(
    recall_client: tuple[TestClient, Database],
) -> None:
    client, database = recall_client
    transcript_id, entry_id = add_recall_transcript(database)

    response = client.post("/v1/recall/search", json={"query": "comet recall"})

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "comet recall"
    assert data["terms"] == ["comet", "recall"]
    assert data["match_query"] == '"comet" "recall"'
    assert data["result_count"] == 1
    assert len(data["results"]) == 1
    hit = data["results"][0]
    assert hit == {
        "result_type": "raw_transcript",
        "rank": 1,
        "score": hit["score"],
        "session_id": "pi-session-recall",
        "transcript_id": transcript_id,
        "transcript_path": "/tmp/pi/recall.jsonl",
        "transcript_entry_id": entry_id,
        "pi_entry_id": "recall-entry-1",
        "entry_type": "message",
        "message_role": "assistant",
        "timestamp": hit["timestamp"],
        "byte_start": 24,
        "byte_end": 124,
        "excerpt": hit["excerpt"],
        "match_reason": "Matched raw transcript text for: comet, recall",
    }
    assert hit["score"] <= 0
    assert datetime.fromisoformat(hit["timestamp"])
    assert "comet" in hit["excerpt"].lower()
    assert "<mark>" in hit["excerpt"]


def test_recall_search_endpoint_returns_empty_results_for_no_match_or_unindexed_data(
    recall_client: tuple[TestClient, Database],
) -> None:
    client, database = recall_client
    add_recall_transcript(database, text="unindexed comet recall line", should_index=False)

    no_match = client.post("/v1/recall/search", json={"query": "missing"})
    unindexed = client.post("/v1/recall/search", json={"query": "comet recall"})

    assert no_match.status_code == 200
    assert no_match.json()["results"] == []
    assert no_match.json()["result_count"] == 0
    assert unindexed.status_code == 200
    assert unindexed.json()["results"] == []
    assert unindexed.json()["result_count"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "comet", "limit": 0},
        {"query": "comet", "limit": 51},
        {"query": "comet", "unexpected": "field"},
    ],
)
def test_recall_search_endpoint_invalid_payload_returns_422(
    recall_client: tuple[TestClient, Database],
    payload: dict[str, object],
) -> None:
    client, _database = recall_client

    response = client.post("/v1/recall/search", json=payload)

    assert response.status_code == 422


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

        response = TestClient(app).get(f"/v1/debug/jobs/{job.id}")
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
        response = TestClient(app).get("/v1/debug/jobs/999")
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
            "repo_name": "basecamp",
        },
        {
            "session_id": "pi-session-1",
            "transcript_path": "/tmp/transcript.jsonl",
            "repo_root": "/workspace/basecamp",
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
