from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pi_memory.analysis import TranscriptAnalysisResult
from pi_memory.constants import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_PROJECT_MEMORY_RECORDS,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
)
from pi_memory.db.database import Database
from pi_memory.infra.job_queue import JobStore
from pi_memory.ingest import IngestResult
from pi_memory.pipeline.reconciliation import EnqueueSpec
from pi_memory.pipeline.stages.assess_interpretation_quality.enqueue import (
    assess_interpretation_quality_idempotency_key,
    assess_interpretation_quality_job_spec,
)
from pi_memory.pipeline.stages.interpret_session.enqueue import (
    interpret_session_idempotency_key,
    interpret_session_job_spec,
)
from pi_memory.pipeline.stages.process_transcript.enqueue import (
    STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    STRUCTURAL_LIVENESS_POLICY_VERSION,
    enqueue_process_transcript_job,
    process_transcript_idempotency_key,
    process_transcript_job_spec,
    process_transcript_job_spec_from_fields,
)
from pi_memory.pipeline.stages.project_memory_records.enqueue import (
    project_memory_records_idempotency_key,
    project_memory_records_job_spec,
)
from pi_memory.pipeline.stages.promote_durable_memory.enqueue import (
    promote_durable_memory_idempotency_key,
    promote_durable_memory_job_spec,
)
from pi_memory.pipeline.stages.summarize_tool_activities.enqueue import (
    summarize_tool_activities_idempotency_key,
    summarize_tool_activities_job_spec,
)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def ingest_result(*, entries_ingested: int = 1) -> IngestResult:
    return IngestResult(
        session_id="pi-session-1",
        transcript_id=42,
        observation_id=7,
        entries_ingested=entries_ingested,
        cursor_offset=120,
        file_size=150,
        observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        malformed_lines=1,
        unsupported_lines=2,
    )


def analysis_result(*, analysis_run_id: int = 101) -> TranscriptAnalysisResult:
    return TranscriptAnalysisResult(
        analysis_run_id=analysis_run_id,
        activity_count=3,
        episode_count=2,
        manifest_count=1,
        snapshot_shell_id=11,
        analyzed_through_entry_id=123,
        analyzed_through_byte_offset=456,
        status="completed",
    )


def test_process_transcript_job_spec_has_expected_payload_for_enqueued_results() -> None:
    result = ingest_result(entries_ingested=4)

    spec = process_transcript_job_spec(result)

    assert isinstance(spec, EnqueueSpec)
    assert spec is not None
    assert spec.kind == JOB_KIND_PROCESS_TRANSCRIPT
    assert spec.payload_json == {
        "transcript_id": 42,
        "session_id": "pi-session-1",
        "observation_id": 7,
        "entries_ingested": 4,
        "cursor_offset": 120,
        "file_size": 150,
        "observed_at": "2026-01-01T12:00:00+00:00",
        "malformed_lines": 1,
        "unsupported_lines": 2,
    }
    assert spec.idempotency_key is None


def test_process_transcript_job_spec_from_fields_includes_structural_target_and_key() -> None:
    spec = process_transcript_job_spec_from_fields(
        transcript_id=42,
        analyzed_through_entry_id=123,
        analyzed_through_byte_offset=456,
        parent_transcript_path="/tmp/parent.jsonl",
        parent_transcript_id=77,
        structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
        liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
        idempotency_key=process_transcript_idempotency_key(
            transcript_id=42,
            analyzed_through_entry_id=123,
            analyzed_through_byte_offset=456,
            parent_transcript_path="/tmp/parent.jsonl",
            parent_transcript_id=77,
            structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
            liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
        ),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_PROCESS_TRANSCRIPT,
        payload_json={
            "transcript_id": 42,
            "analyzed_through_entry_id": 123,
            "analyzed_through_byte_offset": 456,
            "parent_transcript_path": "/tmp/parent.jsonl",
            "parent_transcript_id": 77,
            "structural_analysis_schema_version": STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
            "liveness_policy_version": STRUCTURAL_LIVENESS_POLICY_VERSION,
        },
        idempotency_key=process_transcript_idempotency_key(
            transcript_id=42,
            analyzed_through_entry_id=123,
            analyzed_through_byte_offset=456,
            parent_transcript_path="/tmp/parent.jsonl",
            parent_transcript_id=77,
            structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
            liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
        ),
    )


def test_process_transcript_idempotency_key_includes_structural_target() -> None:
    assert process_transcript_idempotency_key(
        transcript_id=42,
        analyzed_through_entry_id=123,
        analyzed_through_byte_offset=456,
        parent_transcript_path="/tmp/parent.jsonl",
        parent_transcript_id=77,
        structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
        liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
    ) == (
        "process_transcript:42:123:456:/tmp/parent.jsonl:77:schema-v1:liveness-v1"
    )


def test_process_transcript_job_spec_requires_new_entries() -> None:
    assert process_transcript_job_spec(ingest_result(entries_ingested=0)) is None


def test_process_transcript_enqueue_skips_zero_entry_ingest(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        store = JobStore(database=database)
        assert enqueue_process_transcript_job(store, ingest_result(entries_ingested=0)) is None
    finally:
        database.close_if_open()


def test_summarize_tool_activities_job_spec_builds_payload_and_key() -> None:
    result = analysis_result()

    spec = summarize_tool_activities_job_spec(
        transcript_id=42,
        session_id="pi-session-1",
        analysis_result=result,
        process_job_id=55,
        idempotency_key=summarize_tool_activities_idempotency_key(55),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
        payload_json={
            "transcript_id": 42,
            "analysis_run_id": 101,
            "session_id": "pi-session-1",
            "process_job_id": 55,
            "analyzed_through_entry_id": 123,
            "analyzed_through_byte_offset": 456,
            "activity_count": 3,
            "episode_count": 2,
            "manifest_count": 1,
        },
        idempotency_key=summarize_tool_activities_idempotency_key(55),
    )


def test_interpret_session_job_spec_builds_payload_and_key() -> None:
    spec = interpret_session_job_spec(
        transcript_id=42,
        session_id="pi-session-1",
        analysis_run_id=101,
        process_job_id=55,
        analyzed_through_entry_id=123,
        analyzed_through_byte_offset=456,
        activity_count=3,
        episode_count=2,
        manifest_count=1,
        idempotency_key=interpret_session_idempotency_key(88),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_INTERPRET_SESSION,
        payload_json={
            "transcript_id": 42,
            "analysis_run_id": 101,
            "session_id": "pi-session-1",
            "process_job_id": 55,
            "analyzed_through_entry_id": 123,
            "analyzed_through_byte_offset": 456,
            "activity_count": 3,
            "episode_count": 2,
            "manifest_count": 1,
        },
        idempotency_key=interpret_session_idempotency_key(88),
    )


def test_assess_interpretation_quality_job_spec_builds_payload_and_key() -> None:
    spec = assess_interpretation_quality_job_spec(
        snapshot_id=100,
        session_id="pi-session-1",
        interpretation_job_id=55,
        idempotency_key=assess_interpretation_quality_idempotency_key(100),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
        payload_json={
            "snapshot_id": 100,
            "session_id": "pi-session-1",
            "interpretation_job_id": 55,
        },
        idempotency_key=assess_interpretation_quality_idempotency_key(100),
    )


def test_project_memory_records_job_spec_builds_payload_and_retries() -> None:
    spec = project_memory_records_job_spec(
        quality_report_id=77,
        session_id="pi-session-1",
        quality_job_id=55,
        idempotency_key=project_memory_records_idempotency_key(77),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_PROJECT_MEMORY_RECORDS,
        payload_json={
            "scope": "quality_report",
            "quality_report_id": 77,
            "session_id": "pi-session-1",
            "quality_job_id": 55,
        },
        max_attempts=3,
        idempotency_key=project_memory_records_idempotency_key(77),
    )


def test_promote_durable_memory_job_spec_builds_payload_and_retries() -> None:
    spec = promote_durable_memory_job_spec(
        quality_report_id=77,
        session_id="pi-session-1",
        quality_job_id=55,
        idempotency_key=promote_durable_memory_idempotency_key(77),
    )

    assert spec == EnqueueSpec(
        kind=JOB_KIND_PROMOTE_DURABLE_MEMORY,
        payload_json={
            "quality_report_id": 77,
            "session_id": "pi-session-1",
            "quality_job_id": 55,
        },
        max_attempts=5,
        idempotency_key=promote_durable_memory_idempotency_key(77),
    )
