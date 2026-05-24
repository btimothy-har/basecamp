from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pi_memory.constants import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    DURABLE_MEMORY_STATUS_PROMOTED,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_STATUS_CLOSED,
    EPISODE_STATUS_OPEN,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_PROJECT_MEMORY_RECORDS,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_INDEXED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
)
from pi_memory.db.database import Database
from pi_memory.db.models import (
    AnalysisRun,
    DurableMemoryItem,
    Episode,
    Job,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from pi_memory.durable import build_candidate_from_quality_report
from pi_memory.pipeline.reconciliation import GateDecision, Reconciler, ReconciliationReport, ReconciliationRunOptions
from pi_memory.pipeline.stages.assess_interpretation_quality.enqueue import (
    assess_interpretation_quality_idempotency_key,
    assess_interpretation_quality_job_spec,
)
from pi_memory.pipeline.stages.interpret_session.enqueue import interpret_session_idempotency_key
from pi_memory.pipeline.stages.process_transcript.enqueue import (
    STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
    STRUCTURAL_LIVENESS_POLICY_VERSION,
    process_transcript_idempotency_key,
)
from pi_memory.pipeline.stages.project_memory_records.enqueue import project_memory_records_idempotency_key
from pi_memory.pipeline.stages.promote_durable_memory.enqueue import promote_durable_memory_idempotency_key
from pi_memory.pipeline.stages.summarize_tool_activities.enqueue import summarize_tool_activities_idempotency_key
from pi_memory.projection.session_claims import session_claim_content_hash
from sqlalchemy import func, select

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


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


def sample_quality_claim() -> dict[str, object]:
    return {
        "kind": "decision",
        "statement": "Use artifact-aware reconciliation for terminal memory gates.",
        "confidence": 0.9,
        "source_ref_ids": ["activity:1"],
    }


def create_quality_report(database: Database, *, claims: list[dict[str, object]] | None = None) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo/basecamp")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            interpretation_json={"claims": [] if claims is None else claims},
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


def create_claim_quality_report(database: Database) -> tuple[int, int, dict[str, object]]:
    claim = sample_quality_claim()
    report_id = create_quality_report(database, claims=[claim])
    with database.session() as session:
        snapshot_id = session.get_one(SessionInterpretationQualityReport, report_id).snapshot_id
    return report_id, snapshot_id, claim


def create_projection_record_for_claim(
    database: Database,
    *,
    report_id: int,
    snapshot_id: int,
    claim_index: int,
    claim: dict[str, object],
) -> int:
    with database.session() as session:
        record_key = f"session_claim:{snapshot_id}:{claim_index}"
        record = MemoryProjectionRecord(
            collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
            chroma_id=record_key,
            record_key=record_key,
            record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
            memory_layer=MEMORY_LAYER_SHORT_TERM,
            source_table="session_interpretation_snapshots",
            source_id=snapshot_id,
            snapshot_id=snapshot_id,
            quality_report_id=report_id,
            durable_memory_id=None,
            claim_index=claim_index,
            content_hash=session_claim_content_hash(claim),
            embedding_model="test-embedding-model",
            embedding_dimension=3,
            status=MEMORY_PROJECTION_STATUS_INDEXED,
            recall_visible=True,
            relation_visible=True,
            metadata_json={},
            last_error=None,
            indexed_at=BASE_TIME,
        )
        session.add(record)
        session.flush()
        return record.id


def create_terminal_durable_item_for_claim(
    database: Database,
    *,
    report_id: int,
    snapshot_id: int,
    claim_index: int,
) -> int:
    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        candidate = build_candidate_from_quality_report(report, claim_index)
        memory = DurableMemoryItem(
            session_id=report.snapshot.session_id,
            transcript_id=report.snapshot.transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=report_id,
            status=DURABLE_MEMORY_STATUS_PROMOTED,
            claim_index=claim_index,
            claim_kind=candidate.claim_kind,
            statement=candidate.statement,
            confidence=candidate.confidence,
            content_hash=candidate.content_hash,
        )
        session.add(memory)
        session.flush()
        return memory.id


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


def create_transcript_with_entries(
    database: Database,
    *,
    session_id: str,
    path: str,
    entries: tuple[tuple[int, int], ...],
    parent_transcript_path: str | None = None,
    parent_transcript_id: int | None = None,
) -> tuple[int, list[int], list[int]]:
    with database.session() as session:
        memory_session = MemorySession(session_id=session_id, cwd="/repo/basecamp")
        transcript = Transcript(
            session=memory_session,
            path=path,
            parent_transcript_path=parent_transcript_path,
            parent_transcript_id=parent_transcript_id,
            cursor_offset=max(byte_end for _, byte_end in entries),
            file_size=max(byte_end for _, byte_end in entries),
        )
        session.add(transcript)
        session.flush()

        entry_rows: list[TranscriptEntry] = []
        for index, (byte_start, byte_end) in enumerate(entries, start=1):
            entry_rows.append(
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id=f"entry-{index}",
                    entry_type="message",
                    message_role="user",
                    raw_line='{"type":"message","message":{"role":"user","content":"message"}}',
                    byte_start=byte_start,
                    byte_end=byte_end,
                ),
            )
        session.add_all(entry_rows)
        session.flush()

        entry_ids = [entry.id for entry in entry_rows]
        entry_bytes = [entry.byte_end for entry in entry_rows]
        return transcript.id, entry_ids, entry_bytes


def create_structural_analysis_run(
    database: Database,
    transcript_id: int,
    *,
    analyzed_through_entry_id: int,
    analyzed_through_byte_offset: int,
    include_version_metadata: bool = True,
    parent_transcript_path: str | None = None,
    parent_transcript_id: int | None = None,
) -> tuple[int, int | None]:
    with database.session() as session:
        transcript = session.get(Transcript, transcript_id)
        if transcript is None:
            raise RuntimeError

        process_job = Job(
            kind=JOB_KIND_PROCESS_TRANSCRIPT,
            status=JOB_STATUS_COMPLETED,
            payload_json={"transcript_id": transcript_id},
        )
        diagnostics = {
            "phase": "5A",
            "analysis_kind": ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            "entry_count": 2,
        }
        if include_version_metadata:
            diagnostics.update(
                {
                    "structural_analysis_schema_version": STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
                    "liveness_policy_version": STRUCTURAL_LIVENESS_POLICY_VERSION,
                    "parent_transcript_path": (
                        transcript.parent_transcript_path
                        if parent_transcript_path is None
                        else parent_transcript_path
                    ),
                    "parent_transcript_id": (
                        transcript.parent_transcript_id
                        if parent_transcript_id is None
                        else parent_transcript_id
                    ),
                },
            )

        analysis_run = AnalysisRun(
            session=transcript.session,
            transcript=transcript,
            job=process_job,
            analysis_kind=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_entry_id=analyzed_through_entry_id,
            analyzed_through_byte_offset=analyzed_through_byte_offset,
            diagnostics_json=diagnostics,
        )
        session.add_all([process_job, analysis_run])
        session.flush()
        return analysis_run.id, process_job.id


def create_snapshot_shell_for_analysis(
    database: Database,
    analysis_run_id: int,
    *,
    parent_transcript_path: str | None,
    parent_transcript_id: int | None,
    analyzed_through_entry_id: int | None,
    analyzed_through_byte_offset: int,
) -> int:
    with database.session() as session:
        analysis_run = session.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise RuntimeError

        shell = SessionSnapshotShell(
            session_id=analysis_run.session_id,
            transcript_id=analysis_run.transcript_id,
            analysis_run_id=analysis_run_id,
            status=SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
            analyzed_through_entry_id=analyzed_through_entry_id,
            analyzed_through_byte_offset=analyzed_through_byte_offset,
            activity_count=0,
            episode_count=0,
            manifest_count=0,
            tool_pair_count=0,
            snapshot_json={
                "kind": "session_snapshot_shell",
                "fork": {
                    "parent_transcript_path": parent_transcript_path,
                    "parent_transcript_id": parent_transcript_id,
                },
            },
        )
        session.add(shell)
        session.flush()
        return shell.id


def create_completed_summarize_job(database: Database, analysis_run_id: int, process_job_id: int) -> int:
    with database.session() as session:
        analysis_run = session.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise RuntimeError

        summarize_job = Job(
            kind=JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
            idempotency_key=summarize_tool_activities_idempotency_key(process_job_id),
            status=JOB_STATUS_COMPLETED,
            payload_json={
                "transcript_id": analysis_run.transcript_id,
                "analysis_run_id": analysis_run.id,
                "session_id": analysis_run.session.session_id,
                "process_job_id": process_job_id,
            },
        )
        session.add(summarize_job)
        session.flush()
        return summarize_job.id


def create_episode_for_analysis(
    database: Database,
    analysis_run_id: int,
    *,
    ordinal: int,
    status: str,
    close_reason: str,
    first_entry_id: int | None,
    last_entry_id: int | None,
    byte_start: int,
    byte_end: int,
    timestamp_end: datetime | None,
) -> int:
    with database.session() as session:
        analysis_run = session.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise RuntimeError

        episode = Episode(
            analysis_run=analysis_run,
            session=analysis_run.session,
            transcript=analysis_run.transcript,
            ordinal=ordinal,
            status=status,
            close_reason=close_reason,
            first_entry_id=first_entry_id,
            last_entry_id=last_entry_id,
            byte_start=byte_start,
            byte_end=byte_end,
            timestamp_start=timestamp_end,
            timestamp_end=timestamp_end,
            activity_count=1,
            message_count=1,
            tool_pair_count=0,
        )
        session.add(episode)
        session.flush()
        return episode.id


def create_interpretation_snapshot_for_analysis(database: Database, analysis_run_id: int) -> int:
    with database.session() as session:
        analysis_run = session.get(AnalysisRun, analysis_run_id)
        if analysis_run is None:
            raise RuntimeError

        snapshot = SessionInterpretationSnapshot(
            session=analysis_run.session,
            transcript=analysis_run.transcript,
            analysis_run=analysis_run,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            blocked_reason=None,
            analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
            analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
        )
        session.add(snapshot)
        session.flush()
        return snapshot.id


def create_quality_report_for_snapshot(database: Database, snapshot_id: int) -> int:
    with database.session() as session:
        snapshot = session.get(SessionInterpretationSnapshot, snapshot_id)
        if snapshot is None:
            raise RuntimeError

        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            promotable=True,
        )
        session.add(report)
        session.flush()
        return report.id


def find_decision(report: ReconciliationReport, gate: str) -> GateDecision | None:
    """Return the decision for one gate name if present."""
    for decision in report.decisions:
        if decision.target.gate == gate:
            return decision
    return None


def find_decision_by_transcript(
    report: ReconciliationReport,
    gate: str,
    transcript_id: int,
) -> GateDecision | None:
    """Return the decision for one transcript for a given gate."""
    for decision in report.decisions:
        if decision.target.gate != gate:
            continue
        if decision.target.identity.get("transcript_id") == transcript_id:
            return decision
    return None


def test_reconciler_transcript_to_process_reconciles_growth_target(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-1",
            path="/tmp/transcript-1.jsonl",
            entries=((100, 200), (0, 100)),
        )
        create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[1],
            analyzed_through_byte_offset=entry_bytes[1],
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("transcript_to_process",),
            ),
        )

        decision = find_decision(report, "transcript_to_process")
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert decision.enqueue_spec is not None
        assert decision.enqueue_spec.payload_json["transcript_id"] == transcript_id
        assert decision.enqueue_spec.payload_json["analyzed_through_entry_id"] == entry_ids[0]
        assert decision.enqueue_spec.payload_json["analyzed_through_byte_offset"] == entry_bytes[0]
        assert decision.enqueue_spec.idempotency_key == process_transcript_idempotency_key(
            transcript_id=transcript_id,
            analyzed_through_entry_id=entry_ids[0],
            analyzed_through_byte_offset=entry_bytes[0],
            parent_transcript_path=None,
            parent_transcript_id=None,
            structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
            liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
        )
        assert len(report.enqueued_job_ids) == 1
    finally:
        database.close_if_open()


def test_reconciler_transcript_to_process_reports_satisfied_when_target_is_current(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-2",
            path="/tmp/transcript-2.jsonl",
            entries=((0, 100), (100, 200)),
        )
        create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[1],
            analyzed_through_byte_offset=entry_bytes[1],
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("transcript_to_process",),
            ),
        )

        decision = find_decision(report, "transcript_to_process")
        assert decision is not None
        assert decision.status == "satisfied"
        assert not decision.can_enqueue
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_transcript_to_process_reconciles_parent_resolution_change(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        child_transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-3",
            path="/tmp/child-transcript.jsonl",
            entries=((0, 100), (100, 200)),
            parent_transcript_path="/tmp/parent-transcript.jsonl",
        )
        analysis_run_id, _ = create_structural_analysis_run(
            database,
            child_transcript_id,
            analyzed_through_entry_id=entry_ids[1],
            analyzed_through_byte_offset=entry_bytes[1],
            include_version_metadata=False,
        )
        create_snapshot_shell_for_analysis(
            database,
            analysis_run_id,
            parent_transcript_path="/tmp/parent-transcript.jsonl",
            parent_transcript_id=None,
            analyzed_through_entry_id=entry_ids[1],
            analyzed_through_byte_offset=entry_bytes[1],
        )
        parent_id, _, _ = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-parent",
            path="/tmp/parent-transcript.jsonl",
            entries=((0, 50),),
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("transcript_to_process",),
            ),
        )

        decision = find_decision_by_transcript(report, "transcript_to_process", child_transcript_id)
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert decision.enqueue_spec is not None
        assert decision.enqueue_spec.payload_json["parent_transcript_id"] == parent_id
        assert decision.enqueue_spec.payload_json["transcript_id"] == child_transcript_id

        with database.session() as session:
            child_job_ids = tuple(
                job_id
                for job_id in report.enqueued_job_ids
                if (job := session.get(Job, job_id)) is not None
                and job.payload_json.get("transcript_id") == child_transcript_id
            )
            assert len(child_job_ids) == 1
            child_job = session.get(Job, child_job_ids[0])
            assert child_job is not None
            assert child_job.payload_json["transcript_id"] == child_transcript_id
            expected_key = process_transcript_idempotency_key(
                transcript_id=child_transcript_id,
                analyzed_through_entry_id=entry_ids[1],
                analyzed_through_byte_offset=entry_bytes[1],
                parent_transcript_path="/tmp/parent-transcript.jsonl",
                parent_transcript_id=parent_id,
                structural_analysis_schema_version=STRUCTURAL_ANALYSIS_SCHEMA_VERSION,
                liveness_policy_version=STRUCTURAL_LIVENESS_POLICY_VERSION,
            )
            assert child_job.idempotency_key == expected_key
            child = session.get(Transcript, child_transcript_id)
            assert child is not None
            assert child.parent_transcript_id is None
    finally:
        database.close_if_open()


def test_reconciler_transcript_to_process_skips_enqueue_when_unkeyed_active_job_exists(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, _, _ = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-4",
            path="/tmp/transcript-4.jsonl",
            entries=((0, 100),),
        )
        with database.session() as session:
            session.add(
                Job(
                    kind=JOB_KIND_PROCESS_TRANSCRIPT,
                    status=JOB_STATUS_QUEUED,
                    payload_json={"transcript_id": transcript_id},
                ),
            )
            session.commit()

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("transcript_to_process",),
            ),
        )

        decision = find_decision(report, "transcript_to_process")
        assert decision is not None
        assert decision.status == "in_flight"
        assert not decision.can_enqueue
        assert report.enqueued_job_ids == ()

        with database.session() as session:
            assert session.scalar(
                select(func.count()).select_from(Job).where(
                    Job.kind == JOB_KIND_PROCESS_TRANSCRIPT,
                    Job.idempotency_key.is_(None),
                ),
            ) == 1

    finally:
        database.close_if_open()


def test_reconciler_blocks_interpret_for_live_current_cursor_episode(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-live-semantic",
            path="/tmp/live-semantic.jsonl",
            entries=((0, 100), (100, 200)),
        )
        analysis_run_id, process_job_id = create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[1],
            analyzed_through_byte_offset=entry_bytes[1],
        )
        summarize_job_id = create_completed_summarize_job(database, analysis_run_id, process_job_id)
        closed_episode_id = create_episode_for_analysis(
            database,
            analysis_run_id,
            ordinal=0,
            status=EPISODE_STATUS_CLOSED,
            close_reason=EPISODE_CLOSE_REASON_TIME_GAP,
            first_entry_id=entry_ids[0],
            last_entry_id=entry_ids[0],
            byte_start=0,
            byte_end=entry_bytes[0],
            timestamp_end=BASE_TIME - timedelta(hours=2),
        )
        live_episode_id = create_episode_for_analysis(
            database,
            analysis_run_id,
            ordinal=1,
            status=EPISODE_STATUS_OPEN,
            close_reason=EPISODE_CLOSE_REASON_CURRENT_CURSOR,
            first_entry_id=entry_ids[1],
            last_entry_id=entry_ids[1],
            byte_start=entry_bytes[0],
            byte_end=entry_bytes[1],
            timestamp_end=BASE_TIME - timedelta(minutes=30),
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("summarize_to_interpret",),
                as_of=BASE_TIME,
            ),
        )

        decision = find_decision(report, "summarize_to_interpret")
        assert decision is not None
        assert decision.status == "blocked"
        assert not decision.can_enqueue
        assert decision.existing_job_id == summarize_job_id
        assert decision.details["semantic_liveness"] == {
            "as_of": BASE_TIME.isoformat(),
            "total_episode_count": 2,
            "eligible_episode_count": 1,
            "live_episode_count": 1,
            "semantic_analyzed_through_entry_id": entry_ids[0],
            "semantic_analyzed_through_byte_offset": entry_bytes[0],
            "live_episode_ids": (live_episode_id,),
        }
        assert closed_episode_id != live_episode_id
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_enqueues_interpret_for_idle_current_cursor_episode(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-idle-semantic",
            path="/tmp/idle-semantic.jsonl",
            entries=((0, 100),),
        )
        analysis_run_id, process_job_id = create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[0],
            analyzed_through_byte_offset=entry_bytes[0],
        )
        summarize_job_id = create_completed_summarize_job(database, analysis_run_id, process_job_id)
        create_episode_for_analysis(
            database,
            analysis_run_id,
            ordinal=0,
            status=EPISODE_STATUS_OPEN,
            close_reason=EPISODE_CLOSE_REASON_CURRENT_CURSOR,
            first_entry_id=entry_ids[0],
            last_entry_id=entry_ids[0],
            byte_start=0,
            byte_end=entry_bytes[0],
            timestamp_end=BASE_TIME - timedelta(hours=1),
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("summarize_to_interpret",),
                as_of=BASE_TIME,
            ),
        )

        decision = find_decision(report, "summarize_to_interpret")
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert decision.enqueue_spec is not None
        assert decision.details["semantic_liveness"] == {
            "as_of": BASE_TIME.isoformat(),
            "total_episode_count": 1,
            "eligible_episode_count": 1,
            "live_episode_count": 0,
            "semantic_analyzed_through_entry_id": entry_ids[0],
            "semantic_analyzed_through_byte_offset": entry_bytes[0],
            "live_episode_ids": (),
        }
        assert len(report.enqueued_job_ids) == 1

        with database.session() as session:
            interpret_job = session.scalar(
                select(Job).where(
                    Job.kind == JOB_KIND_INTERPRET_SESSION,
                    Job.idempotency_key == interpret_session_idempotency_key(summarize_job_id),
                ),
            )
            assert interpret_job is not None
            assert interpret_job.payload_json["analysis_run_id"] == analysis_run_id
    finally:
        database.close_if_open()


def test_reconciler_blocks_stale_analysis_before_summarize_or_interpret(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-stale-downstream",
            path="/tmp/stale-downstream.jsonl",
            entries=((0, 100), (100, 200)),
        )
        create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[0],
            analyzed_through_byte_offset=entry_bytes[0],
        )

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("analysis_to_summarize", "summarize_to_interpret"),
            ),
        )

        summarize_decision = find_decision(report, "analysis_to_summarize")
        interpret_decision = find_decision(report, "summarize_to_interpret")
        assert summarize_decision is not None
        assert summarize_decision.status == "blocked"
        assert not summarize_decision.can_enqueue
        assert interpret_decision is not None
        assert interpret_decision.status == "blocked"
        assert not interpret_decision.can_enqueue
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_blocks_snapshot_to_quality_for_stale_structural_analysis(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-stale-snapshot",
            path="/tmp/stale-snapshot.jsonl",
            entries=((0, 100), (100, 200)),
        )
        analysis_run_id, _ = create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[0],
            analyzed_through_byte_offset=entry_bytes[0],
        )
        snapshot_id = create_interpretation_snapshot_for_analysis(database, analysis_run_id)

        reconciler = Reconciler(database=database)
        report = reconciler.run_once(
            ReconciliationRunOptions(
                enqueue_missing=True,
                gate_names=("snapshot_to_quality",),
            ),
        )

        decision = find_decision(report, "snapshot_to_quality")
        assert decision is not None
        assert decision.status == "blocked"
        assert not decision.can_enqueue
        assert decision.details["snapshot_id"] == snapshot_id
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_blocks_quality_children_for_stale_structural_analysis(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        transcript_id, entry_ids, entry_bytes = create_transcript_with_entries(
            database,
            session_id="pi-session-structural-stale-quality",
            path="/tmp/stale-quality.jsonl",
            entries=((0, 100), (100, 200)),
        )
        analysis_run_id, _ = create_structural_analysis_run(
            database,
            transcript_id,
            analyzed_through_entry_id=entry_ids[0],
            analyzed_through_byte_offset=entry_bytes[0],
        )
        snapshot_id = create_interpretation_snapshot_for_analysis(database, analysis_run_id)
        quality_report_id = create_quality_report_for_snapshot(database, snapshot_id)

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
        assert project_decision.status == "blocked"
        assert project_decision.details["quality_report_id"] == quality_report_id
        assert promote_decision is not None
        assert promote_decision.status == "blocked"
        assert promote_decision.details["quality_report_id"] == quality_report_id
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


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
        quality_report_id, _, _ = create_claim_quality_report(database)
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


def test_reconciler_treats_no_claim_quality_children_as_satisfied(
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
        assert project_decision.status == "satisfied"
        assert project_decision.details["quality_report_id"] == quality_report_id
        assert promote_decision is not None
        assert promote_decision.status == "satisfied"
        assert promote_decision.details["quality_report_id"] == quality_report_id
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_enqueues_projection_cleanup_for_no_claim_report_with_visible_records(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id = create_quality_report(database)
        with database.session() as session:
            snapshot_id = session.get_one(SessionInterpretationQualityReport, quality_report_id).snapshot_id
        stale_record_id = create_projection_record_for_claim(
            database,
            report_id=quality_report_id,
            snapshot_id=snapshot_id,
            claim_index=0,
            claim=sample_quality_claim(),
        )
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_project",)),
        )

        decision = find_decision(report, "quality_to_project")
        assert decision is not None
        assert decision.status == "missing"
        assert decision.can_enqueue
        assert decision.details["artifact_inspection"]["stale_record_ids"] == (stale_record_id,)
        assert len(report.enqueued_job_ids) == 1
    finally:
        database.close_if_open()


def test_reconciler_treats_indexed_projection_artifact_as_satisfied_without_child_job(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id, snapshot_id, claim = create_claim_quality_report(database)
        projection_record_id = create_projection_record_for_claim(
            database,
            report_id=quality_report_id,
            snapshot_id=snapshot_id,
            claim_index=0,
            claim=claim,
        )
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_project",)),
        )

        decision = find_decision(report, "quality_to_project")
        assert decision is not None
        assert decision.status == "satisfied"
        assert decision.existing_job_id is None
        assert decision.details["artifact_inspection"]["incomplete_record_ids"] == ()
        assert projection_record_id not in report.enqueued_job_ids
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_treats_current_projection_artifact_as_satisfied_despite_failed_child_job(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id, snapshot_id, claim = create_claim_quality_report(database)
        create_projection_record_for_claim(
            database,
            report_id=quality_report_id,
            snapshot_id=snapshot_id,
            claim_index=0,
            claim=claim,
        )
        expected_key = project_memory_records_idempotency_key(quality_report_id)
        with database.session() as session:
            child = Job(
                kind=JOB_KIND_PROJECT_MEMORY_RECORDS,
                idempotency_key=expected_key,
                status=JOB_STATUS_FAILED,
                payload_json={"scope": "quality_report", "quality_report_id": quality_report_id},
            )
            session.add(child)
            session.flush()
            child_job_id = child.id
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_project",)),
        )

        decision = find_decision(report, "quality_to_project")
        assert decision is not None
        assert decision.status == "satisfied"
        assert decision.existing_job_id == child_job_id
        assert decision.details["child_job_status"] == "failed"
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_marks_completed_projection_child_failed_when_artifact_missing(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id, _, _ = create_claim_quality_report(database)
        expected_key = project_memory_records_idempotency_key(quality_report_id)
        with database.session() as session:
            child = Job(
                kind=JOB_KIND_PROJECT_MEMORY_RECORDS,
                idempotency_key=expected_key,
                status=JOB_STATUS_COMPLETED,
                payload_json={"scope": "quality_report", "quality_report_id": quality_report_id},
            )
            session.add(child)
            session.flush()
            child_job_id = child.id
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_project",)),
        )

        decision = find_decision(report, "quality_to_project")
        assert decision is not None
        assert decision.status == "failed"
        assert decision.existing_job_id == child_job_id
        assert decision.details["artifact_inspection"]["missing_claim_indexes"] == (0,)
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_treats_terminal_durable_artifact_as_satisfied_without_child_job(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id, snapshot_id, _ = create_claim_quality_report(database)
        durable_item_id = create_terminal_durable_item_for_claim(
            database,
            report_id=quality_report_id,
            snapshot_id=snapshot_id,
            claim_index=0,
        )
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_promote",)),
        )

        decision = find_decision(report, "quality_to_promote")
        assert decision is not None
        assert decision.status == "satisfied"
        assert decision.existing_job_id is None
        assert decision.details["artifact_inspection"]["content_mismatch_memory_ids"] == ()
        assert durable_item_id not in report.enqueued_job_ids
        assert report.enqueued_job_ids == ()
    finally:
        database.close_if_open()


def test_reconciler_marks_completed_promotion_child_failed_when_packet_artifact_missing(
    tmp_path: Path,
) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        quality_report_id = create_quality_report(
            database,
            claims=[
                {
                    "kind": "decision",
                    "statement": "This claim cannot build a durable packet.",
                    "confidence": 0.9,
                    "source_ref_ids": [],
                },
            ],
        )
        expected_key = promote_durable_memory_idempotency_key(quality_report_id)
        with database.session() as session:
            child = Job(
                kind=JOB_KIND_PROMOTE_DURABLE_MEMORY,
                idempotency_key=expected_key,
                status=JOB_STATUS_COMPLETED,
                payload_json={"quality_report_id": quality_report_id},
                result_json={"failed_packet_count": 1},
            )
            session.add(child)
            session.flush()
            child_job_id = child.id
        reconciler = Reconciler(database=database)

        report = reconciler.run_once(
            ReconciliationRunOptions(enqueue_missing=True, gate_names=("quality_to_promote",)),
        )

        decision = find_decision(report, "quality_to_promote")
        assert decision is not None
        assert decision.status == "failed"
        assert decision.existing_job_id == child_job_id
        assert decision.details["artifact_inspection"]["packet_error_claim_indexes"] == (0,)
        assert report.enqueued_job_ids == ()
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
