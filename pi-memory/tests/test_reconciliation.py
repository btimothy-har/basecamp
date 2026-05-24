from __future__ import annotations

from pathlib import Path

import pytest
from pi_memory.constants import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_PROJECT_MEMORY_RECORDS,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)
from pi_memory.db.database import Database
from pi_memory.db.models import (
    AnalysisRun,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.pipeline.reconciliation import GateDecision, Reconciler, ReconciliationReport, ReconciliationRunOptions
from pi_memory.pipeline.stages.assess_interpretation_quality.enqueue import (
    assess_interpretation_quality_idempotency_key,
    assess_interpretation_quality_job_spec,
)
from pi_memory.pipeline.stages.interpret_session.enqueue import interpret_session_idempotency_key
from pi_memory.pipeline.stages.project_memory_records.enqueue import project_memory_records_idempotency_key
from pi_memory.pipeline.stages.promote_durable_memory.enqueue import promote_durable_memory_idempotency_key
from pi_memory.pipeline.stages.summarize_tool_activities.enqueue import summarize_tool_activities_idempotency_key
from sqlalchemy import func, select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def create_snapshot(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
        )
        session.add(snapshot)
        session.flush()
        return snapshot.id


def create_completed_analysis(database: Database) -> tuple[int, int]:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        transcript = Transcript(session=memory_session, path="/tmp/transcript.jsonl")
        process_job = Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"transcript_id": 1})
        session.add_all([memory_session, transcript, process_job])
        session.flush()

        analysis_run = AnalysisRun(
            session=memory_session,
            transcript=transcript,
            job=process_job,
            analysis_kind=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_byte_offset=456,
            activity_count=3,
            episode_count=1,
            manifest_count=1,
        )
        session.add(analysis_run)
        session.flush()
        return analysis_run.id, process_job.id


def create_quality_report(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            promotable=True,
        )
        session.add(report)
        session.flush()
        return report.id


def create_failed_summarize_artifact(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        transcript = Transcript(session=memory_session, path="/tmp/transcript.jsonl")
        process_job = Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"transcript_id": 1})
        session.add_all([memory_session, transcript, process_job])
        session.flush()

        analysis_run = AnalysisRun(
            session=memory_session,
            transcript=transcript,
            job=process_job,
            analysis_kind=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_byte_offset=456,
        )
        session.add(analysis_run)
        session.flush()

        summarize_job = Job(
            kind=JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
            idempotency_key=summarize_tool_activities_idempotency_key(process_job.id),
            status=JOB_STATUS_FAILED,
            payload_json={
                "transcript_id": transcript.id,
                "analysis_run_id": analysis_run.id,
                "session_id": memory_session.session_id,
                "process_job_id": process_job.id,
            },
        )
        session.add(summarize_job)
        session.flush()
        return summarize_job.id


def find_decision(report: ReconciliationReport, gate: str) -> GateDecision | None:
    """Return the decision for one gate name if present."""
    for decision in report.decisions:
        if decision.target.gate == gate:
            return decision
    return None


def test_reconciler_enqueues_missing_analysis_to_summarize_when_enabled(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id, process_job_id = create_completed_analysis(database)
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("analysis_to_summarize",),
            ),
        )

        decision = find_decision(report, "analysis_to_summarize")
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert len(report.enqueued_job_ids) == 1

        with database.session() as session:
            summarize_job = session.scalar(
                select(Job).where(
                    Job.kind == JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
                    Job.idempotency_key == summarize_tool_activities_idempotency_key(process_job_id),
                ),
            )
            assert summarize_job is not None
            assert summarize_job.payload_json["analysis_run_id"] == analysis_run_id
            assert summarize_job.payload_json["process_job_id"] == process_job_id
    finally:
        database.close_if_open()


def test_reconciler_dry_run_does_not_enqueue_missing_snapshot_to_quality(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        create_snapshot(database)
        reconciler = Reconciler(database=database)

        report = reconciler.run_once()

        snapshot_decision = find_decision(report, "snapshot_to_quality")
        assert snapshot_decision is not None
        assert snapshot_decision.status == "missing"
        assert snapshot_decision.can_enqueue
        assert report.enqueued_job_ids == ()

        with database.session() as session:
            assert session.scalar(select(func.count()).select_from(Job)) == 0
    finally:
        database.close_if_open()


def test_reconciler_enqueues_missing_snapshot_to_quality_when_enabled(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        snapshot_id = create_snapshot(database)
        reconciler = Reconciler(database=database)
        options = ReconciliationRunOptions(enqueue_missing=True)

        report = reconciler.run_once(options)

        snapshot_decision = find_decision(report, "snapshot_to_quality")
        assert snapshot_decision is not None
        assert snapshot_decision.status == "missing"
        assert snapshot_decision.can_enqueue

        expected_spec = assess_interpretation_quality_job_spec(
            snapshot_id=snapshot_id,
            session_id="pi-session-1",
            interpretation_job_id=None,
            idempotency_key=assess_interpretation_quality_idempotency_key(snapshot_id),
        )
        assert len(report.enqueued_job_ids) == 1

        with database.session() as session:
            quality_job = session.scalar(
                select(Job)
                .where(
                    Job.idempotency_key == assess_interpretation_quality_idempotency_key(snapshot_id),
                )
                .order_by(Job.id.asc()),
            )
            assert quality_job is not None
            assert quality_job.payload_json == expected_spec.payload_json
    finally:
        database.close_if_open()


def test_reconciler_enqueues_missing_quality_projection_and_promotion_when_enabled(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id = create_quality_report(database)
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("quality_to_project", "quality_to_promote"),
            ),
        )

        project_decision = find_decision(report, "quality_to_project")
        promote_decision = find_decision(report, "quality_to_promote")
        assert project_decision is not None
        assert project_decision.status == "missing"
        assert promote_decision is not None
        assert promote_decision.status == "missing"
        assert len(report.enqueued_job_ids) == 2

        with database.session() as session:
            project_job = session.scalar(
                select(Job).where(
                    Job.kind == JOB_KIND_PROJECT_MEMORY_RECORDS,
                    Job.idempotency_key == project_memory_records_idempotency_key(quality_report_id),
                ),
            )
            promote_job = session.scalar(
                select(Job).where(
                    Job.kind == JOB_KIND_PROMOTE_DURABLE_MEMORY,
                    Job.idempotency_key == promote_durable_memory_idempotency_key(quality_report_id),
                ),
            )
            assert project_job is not None
            assert project_job.payload_json["scope"] == "quality_report"
            assert project_job.payload_json["quality_report_id"] == quality_report_id
            assert promote_job is not None
            assert promote_job.payload_json["quality_report_id"] == quality_report_id
    finally:
        database.close_if_open()


def test_reconciler_repairs_interpret_job_after_failed_summarize_parent(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        summarize_job_id = create_failed_summarize_artifact(database)
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("summarize_to_interpret",),
            ),
        )

        decision = find_decision(report, "summarize_to_interpret")
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert len(report.enqueued_job_ids) == 1

        with database.session() as session:
            interpret_job = session.scalar(
                select(Job).where(
                    Job.kind == JOB_KIND_INTERPRET_SESSION,
                    Job.idempotency_key == interpret_session_idempotency_key(summarize_job_id),
                ),
            )
            assert interpret_job is not None
            assert interpret_job.payload_json["session_id"] == "pi-session-1"
            assert interpret_job.payload_json["process_job_id"] is not None
    finally:
        database.close_if_open()


@pytest.mark.parametrize("status", [JOB_STATUS_FAILED, JOB_STATUS_CANCELLED])
def test_reconciler_terminal_snapshot_to_quality_jobs_dont_reenqueue(
    tmp_path: Path,
    status: str,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        snapshot_id = create_snapshot(database)
        expected_key = assess_interpretation_quality_idempotency_key(snapshot_id)
        expected_spec = assess_interpretation_quality_job_spec(
            snapshot_id=snapshot_id,
            session_id="pi-session-1",
            interpretation_job_id=None,
            idempotency_key=expected_key,
        )

        with database.session() as session:
            terminal_job = Job(
                kind="assess_interpretation_quality",
                idempotency_key=expected_key,
                status=status,
                payload_json=expected_spec.payload_json,
            )
            session.add(terminal_job)

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(ReconciliationRunOptions(enqueue_missing=True))

        snapshot_decision = find_decision(report, "snapshot_to_quality")
        assert snapshot_decision is not None
        if status == JOB_STATUS_FAILED:
            assert snapshot_decision.status == "failed"
        else:
            assert snapshot_decision.status == "blocked"
        assert not snapshot_decision.can_enqueue
        assert report.enqueued_job_ids == ()

        with database.session() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Job)
                    .where(
                        Job.idempotency_key == expected_key,
                        Job.kind == "assess_interpretation_quality",
                    ),
                )
                == 1
            )
    finally:
        database.close_if_open()
