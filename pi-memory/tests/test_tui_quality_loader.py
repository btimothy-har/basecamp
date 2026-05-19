from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import (
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_KIND_USER_TEXT,
    ANALYSIS_STATUS_COMPLETED,
    EPISODE_INTERPRETATION_STATUS_FAILED,
    EPISODE_STATUS_OPEN,
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
    ActivityUnit,
    AnalysisRun,
    Database,
    Episode,
    EpisodeInterpretationSnapshot,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
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

            failed_analysis = AnalysisRun(
                session_id=failed_session.id,
                transcript_id=failed_transcript.id,
                status=ANALYSIS_STATUS_COMPLETED,
            )
            failed_episode = Episode(
                analysis_run=failed_analysis,
                session_id=failed_session.id,
                transcript_id=failed_transcript.id,
                ordinal=0,
                status=EPISODE_STATUS_OPEN,
                byte_start=0,
                byte_end=20,
            )
            db_session.add(failed_episode)
            db_session.flush()
            db_session.add(
                EpisodeInterpretationSnapshot(
                    session_id=failed_session.id,
                    transcript_id=failed_transcript.id,
                    analysis_run_id=failed_analysis.id,
                    episode_id=failed_episode.id,
                    job_id=failed_job.id,
                    status=EPISODE_INTERPRETATION_STATUS_FAILED,
                    episode_ordinal=0,
                    activity_count=1,
                    claim_source_activity_count=1,
                    failure_metadata_json={"error_type": "RuntimeError"},
                ),
            )

            snapshot = SessionInterpretationSnapshot(
                session_id=reported_session.id,
                transcript_id=reported_transcript.id,
                job_id=reported_job.id,
                status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                blocked_reason=None,
                interpretation_json={
                    "aggregation": {
                        "coverage_status": "partial",
                        "claim_source_episode_count": 2,
                        "completed_episode_count": 1,
                        "failed_episode_count": 1,
                        "skipped_episode_count": 0,
                    },
                },
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
    quality_row = next(row for row in data.rows if row.row_type == "quality_report")
    failure_row = next(row for row in data.rows if row.row_type == "interpretation_failure")
    assert quality_row.detail["episode_interpretation"]["coverage_status"] == "partial"
    assert quality_row.detail["episode_interpretation"]["failed_episode_count"] == 1
    assert failure_row.detail["episode_interpretation"]["coverage_status"] == "failed"
    assert failure_row.detail["episode_interpretation"]["failed_episode_count"] == 1


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

            reported_transcript = Transcript(
                session_id=reported_session.id,
                path="/tmp/reported.jsonl",
                file_size=2048,
                cursor_offset=2048,
            )
            failed_transcript = Transcript(session_id=failed_session.id, path="/tmp/failed.jsonl", file_size=1024)
            db_session.add_all([reported_transcript, failed_transcript])
            db_session.flush()

            reported_entry = TranscriptEntry(
                transcript_id=reported_transcript.id,
                entry_type="message",
                message_role="user",
                timestamp=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
                raw_line='{"type":"message"}',
                byte_start=0,
                byte_end=20,
            )
            failed_entry = TranscriptEntry(
                transcript_id=failed_transcript.id,
                entry_type="message",
                message_role="assistant",
                timestamp=datetime(2026, 5, 1, 12, 5, tzinfo=UTC),
                raw_line='{"type":"message"}',
                byte_start=0,
                byte_end=20,
            )
            db_session.add_all([reported_entry, failed_entry])
            db_session.flush()

            analysis_run = AnalysisRun(
                session_id=reported_session.id,
                transcript_id=reported_transcript.id,
                status=ANALYSIS_STATUS_COMPLETED,
            )
            db_session.add(analysis_run)
            db_session.flush()
            db_session.add_all(
                [
                    ActivityUnit(
                        analysis_run_id=analysis_run.id,
                        session_id=reported_session.id,
                        transcript_id=reported_transcript.id,
                        ordinal=0,
                        kind=ACTIVITY_KIND_USER_TEXT,
                        byte_start=0,
                        byte_end=10,
                    ),
                    ActivityUnit(
                        analysis_run_id=analysis_run.id,
                        session_id=reported_session.id,
                        transcript_id=reported_transcript.id,
                        ordinal=1,
                        kind=ACTIVITY_KIND_TOOL_PAIR,
                        byte_start=10,
                        byte_end=20,
                    ),
                    Episode(
                        analysis_run_id=analysis_run.id,
                        session_id=reported_session.id,
                        transcript_id=reported_transcript.id,
                        ordinal=0,
                        status=EPISODE_STATUS_OPEN,
                        byte_start=0,
                        byte_end=20,
                    ),
                ],
            )

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
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overview = str(app.query_one("#quality-overview").render())
        distribution = str(app.query_one("#quality-distribution").render())
        help_text = str(app.query_one("#quality-help").render())
        table = app.query_one("#quality-table")

        assert "Memory quality overview" in overview
        assert "Coverage" in overview
        assert "Confidence" in overview
        assert "Transcript assessment outcomes" in distribution
        assert "Evidence filters" in help_text
        assert "needs attention" not in f"{overview} {distribution} {help_text}".lower()
        assert table.row_count == 2
        assert [str(cell) for cell in table.get_row_at(0)[:5]] == [
            "1 reported.jsonl",
            "reported-session",
            "healthy",
            "promotable",
            "ent 1 | act 2 | ep 1",
        ]
        detail_text = str(app.query_one("#quality-detail").render()).lower()
        assert "transcript 1 reported.jsonl" in detail_text
        assert "structure: ent=1 act=2 ep=1 tools=1 session-tx=1" in detail_text
        assert "timeline: 2026-05-01 12:00" in detail_text
        assert "file=2k" in detail_text
        assert "job" not in detail_text

        await pilot.press("f")
        await pilot.pause()

        assert table.row_count == 1
        assert [str(cell) for cell in table.get_row_at(0)[:5]] == [
            "2 failed.jsonl",
            "failed-session",
            "no quality report",
            "no report",
            "ent 1 | act 0 | ep 0",
        ]
        gap_detail_text = str(app.query_one("#quality-detail").render()).lower()
        assert "quality report: none for this transcript" in gap_detail_text
        assert "job" not in gap_detail_text
        await pilot.press("q")
