from pathlib import Path

import pytest
from pi_memory.db import (
    JOB_KIND_INTERPRET_SESSION,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    Database,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.tui.quality import QualityTuiApp, load_quality_dashboard_data


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_quality_dashboard_loader_reads_reports_and_unreported_failures(tmp_path: Path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    database = Database(db_url)
    database.initialize()
    try:
        with database.session() as db_session:
            reported_session = MemorySession(session_id="reported-session", repo_name="basecamp", worktree_label="wt")
            failed_session = MemorySession(session_id="failed-session", repo_name="basecamp", worktree_label="wt")
            other_session = MemorySession(session_id="other-session", repo_name="basecamp", worktree_label="wt")
            db_session.add_all([reported_session, failed_session, other_session])
            db_session.flush()

            reported_transcript = Transcript(session_id=reported_session.id, path="/tmp/reported.jsonl")
            failed_transcript = Transcript(session_id=failed_session.id, path="/tmp/failed.jsonl")
            other_transcript = Transcript(session_id=other_session.id, path="/tmp/other.jsonl")
            db_session.add_all([reported_transcript, failed_transcript, other_transcript])
            db_session.flush()

            reported_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_FAILED,
                payload_json={"session_id": reported_session.session_id, "transcript_id": reported_transcript.id},
                last_error="covered by quality report",
            )
            failed_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_FAILED,
                payload_json={"session_id": failed_session.session_id, "transcript_id": failed_transcript.id},
                last_error="interpreter failed",
            )
            db_session.add_all([reported_job, failed_job])
            db_session.flush()

            snapshot = SessionInterpretationSnapshot(
                session_id=reported_session.id,
                transcript_id=reported_transcript.id,
                job_id=reported_job.id,
                status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                blocked_reason=None,
                interpretation_json={},
            )
            db_session.add(snapshot)
            db_session.flush()
            db_session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot.id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
                    quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
                    derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
                    deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
                    semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
                    promotable=False,
                    deterministic_findings_json=[{"severity": "warning"}],
                    semantic_findings_json=[{"severity": "critical"}],
                    assessment_metadata_json={"quality_reference_defect_count": 2},
                ),
            )
    finally:
        database.close_if_open()

    data = load_quality_dashboard_data(db_url)

    assert data.transcript_count == 3
    assert data.row_count == 2
    assert data.quality_report_count == 1
    assert data.failed_interpretation_count == 1
    assert data.promotable_count == 0
    assert data.non_promotable_count == 2
    assert data.quality_status_counts == {SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED: 1}
    assert data.quality_reference_defect_report_count == 1
    assert data.quality_reference_defect_count == 2
    assert {row.row_type for row in data.rows} == {"quality_report", "interpretation_failure"}


def test_quality_dashboard_loader_deduplicates_failed_jobs_by_reported_session_id(tmp_path: Path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    database = Database(db_url)
    database.initialize()
    try:
        with database.session() as db_session:
            memory_session = MemorySession(session_id="reported-session", repo_name="basecamp", worktree_label="wt")
            db_session.add(memory_session)
            db_session.flush()

            transcript = Transcript(session_id=memory_session.id, path="/tmp/reported.jsonl")
            db_session.add(transcript)
            db_session.flush()

            snapshot_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_COMPLETED,
                payload_json={"session_id": memory_session.session_id, "transcript_id": transcript.id},
            )
            duplicate_failed_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_FAILED,
                payload_json={"session_id": memory_session.session_id, "transcript_id": transcript.id},
                last_error="stale failed interpretation",
            )
            db_session.add_all([snapshot_job, duplicate_failed_job])
            db_session.flush()

            snapshot = SessionInterpretationSnapshot(
                session_id=memory_session.id,
                transcript_id=transcript.id,
                job_id=snapshot_job.id,
                status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                blocked_reason=None,
                interpretation_json={},
            )
            db_session.add(snapshot)
            db_session.flush()
            db_session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot.id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    quality_reason=None,
                    derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
                    deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
                    semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
                    promotable=True,
                ),
            )
            duplicate_failed_job_id = duplicate_failed_job.id
    finally:
        database.close_if_open()

    data = load_quality_dashboard_data(db_url)

    assert data.row_count == 1
    assert data.failed_interpretation_count == 0
    assert data.rows[0].row_type == "quality_report"
    assert data.rows[0].session_id == "reported-session"
    assert data.rows[0].detail["snapshot_job_id"] != duplicate_failed_job_id


def test_quality_dashboard_loader_aggregates_promotable_reports_without_failure_statuses(tmp_path: Path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    database = Database(db_url)
    database.initialize()
    try:
        with database.session() as db_session:
            reported_session = MemorySession(session_id="promotable-session", repo_name="basecamp", worktree_label="wt")
            failed_session = MemorySession(session_id="failed-session", repo_name="basecamp", worktree_label="wt")
            db_session.add_all([reported_session, failed_session])
            db_session.flush()

            reported_transcript = Transcript(session_id=reported_session.id, path="/tmp/promotable.jsonl")
            failed_transcript = Transcript(session_id=failed_session.id, path="/tmp/failed.jsonl")
            db_session.add_all([reported_transcript, failed_transcript])
            db_session.flush()

            snapshot_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_COMPLETED,
                payload_json={"session_id": reported_session.session_id, "transcript_id": reported_transcript.id},
            )
            failed_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_FAILED,
                payload_json={"session_id": failed_session.session_id, "transcript_id": failed_transcript.id},
                last_error="interpreter failed",
            )
            db_session.add_all([snapshot_job, failed_job])
            db_session.flush()

            snapshot = SessionInterpretationSnapshot(
                session_id=reported_session.id,
                transcript_id=reported_transcript.id,
                job_id=snapshot_job.id,
                status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                blocked_reason=None,
                interpretation_json={},
            )
            db_session.add(snapshot)
            db_session.flush()
            db_session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot.id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    quality_reason=None,
                    derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
                    deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
                    semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
                    promotable=True,
                ),
            )
    finally:
        database.close_if_open()

    data = load_quality_dashboard_data(db_url)

    assert data.row_count == 2
    assert data.quality_report_count == 1
    assert data.failed_interpretation_count == 1
    assert data.promotable_count == 1
    assert data.non_promotable_count == 1
    assert data.quality_status_counts == {SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY: 1}
    assert "interpretation_failed" not in data.quality_status_counts


@pytest.mark.asyncio
async def test_quality_tui_opens_with_dashboard_overview_and_evidence_table(tmp_path: Path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    database = Database(db_url)
    database.initialize()
    try:
        with database.session() as db_session:
            reported_session = MemorySession(session_id="reported-session", repo_name="basecamp", worktree_label="wt")
            failed_session = MemorySession(session_id="failed-session", repo_name="basecamp", worktree_label="wt")
            db_session.add_all([reported_session, failed_session])
            db_session.flush()

            reported_transcript = Transcript(session_id=reported_session.id, path="/tmp/reported.jsonl")
            failed_transcript = Transcript(session_id=failed_session.id, path="/tmp/failed.jsonl")
            db_session.add_all([reported_transcript, failed_transcript])
            db_session.flush()

            snapshot_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_COMPLETED,
                payload_json={"session_id": reported_session.session_id, "transcript_id": reported_transcript.id},
            )
            failed_job = Job(
                kind=JOB_KIND_INTERPRET_SESSION,
                status=JOB_STATUS_FAILED,
                payload_json={"session_id": failed_session.session_id, "transcript_id": failed_transcript.id},
                last_error="interpreter failed",
            )
            db_session.add_all([snapshot_job, failed_job])
            db_session.flush()

            snapshot = SessionInterpretationSnapshot(
                session_id=reported_session.id,
                transcript_id=reported_transcript.id,
                job_id=snapshot_job.id,
                status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                blocked_reason=None,
                interpretation_json={},
            )
            db_session.add(snapshot)
            db_session.flush()
            db_session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot.id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    quality_reason=None,
                    derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
                    deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
                    semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
                    promotable=True,
                ),
            )
    finally:
        database.close_if_open()

    app = QualityTuiApp(db_url)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        overview = str(app.query_one("#quality-overview").render())
        distribution = str(app.query_one("#quality-distribution").render())
        help_text = str(app.query_one("#quality-help").render())
        table = app.query_one("#quality-table")

        assert "Memory quality overview" in overview
        assert "Coverage" in overview
        assert "Confidence" in overview
        assert "Assessment outcomes and coverage gaps" in distribution
        assert "Evidence filters" in help_text
        assert "needs attention" not in f"{overview} {distribution} {help_text}".lower()
        assert table.row_count == 2

        await pilot.press("f")
        await pilot.pause()

        assert table.row_count == 1
        assert [str(cell) for cell in table.get_row_at(0)[:3]] == [
            "coverage gap",
            "interpretation gap",
            "no report",
        ]
        await pilot.press("q")
