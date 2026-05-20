"""Minimal pi-memory job runner."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pi_memory.analysis import analyze_transcript_structure
from pi_memory.db import (
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_TEXT_KIND_TOOL_SUMMARY,
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ACTIVITY_TEXT_STATUS_FAILED,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
    EPISODE_INTERPRETATION_STATUS_COMPLETED,
    EPISODE_INTERPRETATION_STATUS_FAILED,
    EPISODE_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_PROJECT_MEMORY_RECORDS,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    MEMORY_PROJECTION_STATUS_DELETED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    SOURCE_ORIGIN_UNKNOWN,
    SOURCE_ORIGINS,
    ActivityUnit,
    AnalysisRun,
    Database,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemorySource,
    EpisodeInterpretationSnapshot,
    Job,
    MemoryProjectionRecord,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
    database,
)
from pi_memory.durable import (
    CandidateEvaluator,
    DeterministicDurableMemoryReducer,
    DurableMemoryEvidencePacket,
    DurableMemoryPacketError,
    DurableMemoryProjectionError,
    ReducerContext,
    assess_durable_memory_relations,
    build_durable_memory_evidence_packet,
    create_candidate_evaluator,
    persist_reducer_decision,
    project_durable_memory_record,
)
from pi_memory.durable.relations import RelationAssessmentResult
from pi_memory.interpretation import (
    INTERPRETATION_SCHEMA_VERSION,
    EpisodeInterpretationCoverage,
    EpisodeInterpretationFailureMetadata,
    InterpretationOutput,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
    SessionInterpreter,
    ToolActivitySourceEntry,
    ToolActivitySummarizer,
    ToolActivitySummaryInput,
    ToolActivitySummaryResult,
    ValidatedInterpretation,
    build_episode_interpretation_packet,
    build_interpretation_packet,
    create_session_interpreter,
    create_tool_activity_summarizer,
    validate_episode_interpretation_output,
    validate_interpretation_output,
)
from pi_memory.interpretation.packets import EpisodePacket, InterpretationPacket, InterpretationReadiness
from pi_memory.jobs.interpretation import (
    enqueue_assess_interpretation_quality_job,
    enqueue_interpret_session_job_for_analysis,
    enqueue_project_memory_records_job,
    enqueue_promote_durable_memory_job,
    enqueue_summarize_tool_activities_job,
)
from pi_memory.jobs.store import JobStore
from pi_memory.projection import create_memory_projection, project_session_claims
from pi_memory.projection.contracts import MemoryProjection
from pi_memory.quality import (
    QualityAssessor,
    QualityReportDraft,
    assess_deterministic_interpretation_quality,
    build_quality_packet,
    create_quality_assessor,
)
from pi_memory.recall import index_transcript
from pi_memory.settings import settings as memory_settings

EXPECTED_OBJECT_PAYLOAD_ERROR = "expected object payload"
TRANSCRIPT_ID_INTEGER_ERROR = "transcript_id must be an integer"
ANALYSIS_RUN_ID_INTEGER_ERROR = "analysis_run_id must be an integer"
PROCESS_JOB_ID_INTEGER_ERROR = "process_job_id must be an integer"
SNAPSHOT_ID_INTEGER_ERROR = "snapshot_id must be an integer"
QUALITY_REPORT_ID_INTEGER_ERROR = "quality_report_id must be an integer"
PROJECT_MEMORY_SCOPE_ERROR = "memory projection scope must be 'quality_report' or 'all'"
PROMOTION_TERMINAL_STATUSES = {
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
}

type CandidateUpsertOutcome = Literal["created", "updated", "skipped"]


@dataclass(frozen=True)
class ToolActivitySummaryWorkItem:
    """Tool-pair activity input prepared for summarization outside a DB transaction."""

    activity_unit_id: int
    summary_input: ToolActivitySummaryInput


@dataclass(frozen=True)
class ToolActivitySummaryOutcome:
    """Result of summarizing one tool-pair activity."""

    activity_unit_id: int
    result: ToolActivitySummaryResult | None = None
    error_type: str | None = None


@dataclass(frozen=True)
class ToolActivitySummaryContext:
    """Safe context needed to summarize tool activities and enqueue interpretation."""

    transcript_id: int
    session_id: str
    analysis_run_id: int
    process_job_id: int | None
    analyzed_through_entry_id: int | None
    analyzed_through_byte_offset: int
    activity_count: int
    episode_count: int
    manifest_count: int
    work_items: tuple[ToolActivitySummaryWorkItem, ...]


@dataclass(frozen=True)
class EpisodeInterpretationOutcome:
    """Persistable result for interpreting one episode."""

    episode: EpisodePacket
    packet: InterpretationPacket
    status: str
    validated: ValidatedInterpretation | None = None
    interpreter_result: InterpretationResult | None = None
    failure_metadata: dict[str, Any] | None = None
    error: Exception | None = None


class JobRunnerError(RuntimeError):
    """Base class for job runner errors."""


class PermanentJobError(JobRunnerError):
    """Raised when malformed job data cannot be fixed by retrying."""


class UnsupportedJobKindError(PermanentJobError):
    """Raised when the runner does not support a job kind."""

    def __init__(self, kind: str) -> None:
        super().__init__(f"Unsupported job kind: {kind}")


class InvalidJobPayloadError(PermanentJobError):
    """Raised when a job payload is missing required fields or has invalid values."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid job payload: {message}")


class TranscriptNotFoundError(PermanentJobError):
    """Raised when a job references a missing transcript."""

    def __init__(self, transcript_id: int) -> None:
        super().__init__(f"Transcript {transcript_id} was not found")


class MemoryProjectionJobError(JobRunnerError):
    """Raised when a projection job should be retried safely."""

    def __init__(self) -> None:
        super().__init__("memory projection failed for one or more quality-report claims")


class JobRunner:
    """Run a claimed durable job to completion or recorded failure."""

    def __init__(
        self,
        database: Database = database,
        interpreter: SessionInterpreter | None = None,
        tool_summarizer: ToolActivitySummarizer | None = None,
        quality_assessor: QualityAssessor | None = None,
        memory_projection: MemoryProjection | None = None,
        candidate_evaluator: CandidateEvaluator | None = None,
        durable_reducer: DeterministicDurableMemoryReducer | None = None,
    ) -> None:
        self._database = database
        self._store = JobStore(database=database)
        self._interpreter = interpreter
        self._tool_summarizer = tool_summarizer
        self._quality_assessor_adapter = quality_assessor
        self._memory_projection_adapter = memory_projection
        self._candidate_evaluator_adapter = candidate_evaluator
        self._durable_reducer = durable_reducer or DeterministicDurableMemoryReducer()

    def run(
        self,
        job_id: int,
        run_id: str,
        *,
        running_pid: int | None = None,
        now: datetime | None = None,
    ) -> Job:
        """Start, dispatch, and finish a claimed job."""
        job = self._store.start(
            job_id,
            run_id,
            running_pid=os.getpid() if running_pid is None else running_pid,
            now=now,
        )

        try:
            result_json = self._dispatch(job)
        except (InterpretationValidationError, InterpreterUnavailableError) as error:
            self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=False, now=now)
            raise
        except PermanentJobError as error:
            self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=False, now=now)
            raise
        except Exception as error:
            if _is_final_quality_attempt(job):
                self._write_assessment_failed_quality_report(job, error_type=type(error).__name__)
                self._store.fail(job_id, run_id, error=type(error).__name__, exit_code=1, retry=False, now=now)
            else:
                self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=True, now=now)
            raise

        return self._store.complete(job_id, run_id, result_json=result_json, exit_code=0, now=now)

    def _dispatch(self, job: Job) -> dict[str, Any]:
        if job.kind == JOB_KIND_PROCESS_TRANSCRIPT:
            return self._process_transcript(job)
        if job.kind == JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES:
            return self._summarize_tool_activities(job)
        if job.kind == JOB_KIND_INTERPRET_SESSION:
            return self._interpret_session(job)
        if job.kind == JOB_KIND_ASSESS_INTERPRETATION_QUALITY:
            return self._assess_interpretation_quality(job)
        if job.kind == JOB_KIND_PROJECT_MEMORY_RECORDS:
            return self._project_memory_records(job)
        if job.kind == JOB_KIND_PROMOTE_DURABLE_MEMORY:
            return self._promote_durable_memory(job)
        raise UnsupportedJobKindError(job.kind)

    def _process_transcript(self, job: Job) -> dict[str, Any]:
        transcript_id = _payload_transcript_id(job.payload_json)
        self._database.initialize()
        with self._database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            index_result = index_transcript(session, transcript_id)
            analysis_result = analyze_transcript_structure(session, transcript, job_id=job.id)
            result_json = {
                "transcript_id": transcript.id,
                "session_id": transcript.session.session_id,
                "entry_count": index_result.total_entries,
                "cursor_offset": transcript.cursor_offset,
                "file_size": transcript.file_size,
                "indexed_entry_count": index_result.indexed_entries,
                "phase_5a": analysis_result.to_result_json(),
            }

        summarize_job = enqueue_summarize_tool_activities_job(
            self._store,
            transcript_id=transcript_id,
            session_id=result_json["session_id"],
            analysis_result=analysis_result,
            process_job_id=job.id,
        )
        result_json["summarize_tool_activities_job_id"] = summarize_job.id
        return result_json

    def _summarize_tool_activities(self, job: Job) -> dict[str, Any]:
        transcript_id, analysis_run_id, process_job_id = _payload_summarize_tool_activities(job.payload_json)
        self._database.initialize()
        with self._database.session() as session:
            context = _tool_activity_summary_context(
                session=session,
                transcript_id=transcript_id,
                analysis_run_id=analysis_run_id,
                process_job_id=process_job_id,
            )
            if context is None:
                return _tool_summary_stale_result_json(
                    transcript_id=transcript_id,
                    analysis_run_id=analysis_run_id,
                    process_job_id=process_job_id,
                )

        outcomes = self._summarize_tool_activity_work(context.work_items)
        with self._database.session() as session:
            if _is_stale_analysis_run(session, transcript_id, analysis_run_id) or _is_stale_process_job(
                session,
                transcript_id,
                process_job_id,
            ):
                return _tool_summary_stale_result_json(
                    transcript_id=transcript_id,
                    analysis_run_id=analysis_run_id,
                    process_job_id=process_job_id,
                )
            _apply_tool_summary_outcomes(session, outcomes)

        result_json = _tool_summary_result_json(context, outcomes)
        interpret_job = enqueue_interpret_session_job_for_analysis(
            self._store,
            transcript_id=context.transcript_id,
            session_id=context.session_id,
            analysis_run_id=context.analysis_run_id,
            process_job_id=context.process_job_id,
            analyzed_through_entry_id=context.analyzed_through_entry_id,
            analyzed_through_byte_offset=context.analyzed_through_byte_offset,
            activity_count=context.activity_count,
            episode_count=context.episode_count,
            manifest_count=context.manifest_count,
        )
        result_json["interpret_session_job_id"] = interpret_job.id
        return result_json

    def _summarize_tool_activity_work(
        self,
        work_items: tuple[ToolActivitySummaryWorkItem, ...],
    ) -> list[ToolActivitySummaryOutcome]:
        if not work_items:
            return []

        summarizer = self._tool_activity_summarizer()
        return asyncio.run(
            _summarize_tool_activity_work(
                summarizer,
                work_items,
                concurrency=memory_settings.tool_summary_concurrency,
            ),
        )

    def _interpret_session(self, job: Job) -> dict[str, Any]:
        transcript_id, analysis_run_id, process_job_id = _payload_interpret_session(job.payload_json)
        self._database.initialize()
        packet_for_model: InterpretationPacket | None = None
        snapshot_id: int | None = None
        stable_session_id = ""
        result_json: dict[str, Any] = {}
        with self._database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            packet = build_interpretation_packet(session, transcript, analysis_run_id=analysis_run_id)
            if packet.readiness.is_stale or _is_stale_process_job(session, transcript_id, process_job_id):
                return _stale_result_json(packet)

            if packet.readiness.blocked_reason is not None:
                snapshot = _replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_BLOCKED,
                    blocked_reason=packet.readiness.blocked_reason,
                )
                result_json = _snapshot_result_json(packet, snapshot)
                snapshot_id = snapshot.id
                stable_session_id = packet.readiness.stable_session_id
            elif packet.readiness.should_skip_model:
                outcomes = _skipped_episode_outcomes(packet)
                _replace_episode_interpretation_snapshots(session=session, job=job, packet=packet, outcomes=outcomes)
                snapshot = _replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
                )
                result_json = _snapshot_result_json(packet, snapshot)
                snapshot_id = snapshot.id
                stable_session_id = packet.readiness.stable_session_id
            else:
                packet_for_model = packet
                snapshot_id = None
                stable_session_id = packet.readiness.stable_session_id
                result_json = {}

        if packet_for_model is not None:
            outcomes = self._interpret_episode_outcomes(packet_for_model)
            failure_error: Exception | None = None
            with self._database.session() as session:
                transcript = session.get(Transcript, transcript_id)
                if transcript is None:
                    raise TranscriptNotFoundError(transcript_id)

                packet = build_interpretation_packet(session, transcript, analysis_run_id=analysis_run_id)
                if packet.readiness.is_stale or _is_stale_process_job(session, transcript_id, process_job_id):
                    return _stale_result_json(packet)

                _replace_episode_interpretation_snapshots(session=session, job=job, packet=packet, outcomes=outcomes)
                if _completed_episode_outcome_count(outcomes) == 0:
                    failure_error = _all_episode_interpretations_failed_error(outcomes)
                    snapshot_id = None
                    stable_session_id = packet.readiness.stable_session_id
                    result_json = _episode_failure_result_json(packet, outcomes)
                else:
                    interpretation, interpreter_result = _aggregate_episode_interpretations(packet, outcomes)
                    snapshot = _replace_interpretation_snapshot(
                        session=session,
                        job=job,
                        transcript=transcript,
                        packet=packet,
                        status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                        interpretation=interpretation,
                        interpreter_result=interpreter_result,
                    )
                    result_json = _snapshot_result_json(packet, snapshot)
                    snapshot_id = snapshot.id
                    stable_session_id = packet.readiness.stable_session_id
            if failure_error is not None:
                raise failure_error

        if snapshot_id is None:
            return result_json

        quality_job = enqueue_assess_interpretation_quality_job(
            self._store,
            snapshot_id=snapshot_id,
            session_id=stable_session_id,
            interpretation_job_id=job.id,
        )
        result_json["assess_interpretation_quality_job_id"] = quality_job.id
        return result_json

    def _interpret_episode_outcomes(self, packet: InterpretationPacket) -> tuple[EpisodeInterpretationOutcome, ...]:
        interpreter = self._session_interpreter()
        outcomes: list[EpisodeInterpretationOutcome] = []
        for episode in packet.episode_packets:
            episode_packet = build_episode_interpretation_packet(packet, episode)
            if episode.claim_source_activity_count == 0:
                outcomes.append(_skipped_episode_outcome(episode_packet, episode))
                continue
            try:
                result = interpreter.interpret(episode_packet)
                validated = validate_episode_interpretation_output(result.output, packet, episode)
            except Exception as error:
                outcomes.append(_failed_episode_outcome(episode_packet, episode, error))
            else:
                outcomes.append(_completed_episode_outcome(episode_packet, episode, validated, result))
        return tuple(outcomes)

    def _assess_interpretation_quality(self, job: Job) -> dict[str, Any]:
        snapshot_id = _payload_snapshot_id(job.payload_json)
        self._database.initialize()
        with self._database.session() as session:
            snapshot = session.get(SessionInterpretationSnapshot, snapshot_id)
            if snapshot is None:
                return {
                    "status": "stale",
                    "snapshot_id": snapshot_id,
                    "quality_report_id": None,
                    "stale_reason": "snapshot_not_found",
                }
            draft = assess_deterministic_interpretation_quality(session, snapshot)
            if (
                snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED
                and draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING
            ):
                packet = build_quality_packet(session, snapshot, deterministic_report=draft)
                draft = self._quality_assessor().assess(packet)
            report = _replace_quality_report(session=session, job=job, snapshot=snapshot, draft=draft)
            result_json = _quality_report_result_json(snapshot, report)

        # Always enqueue; downstream jobs are safe no-ops or rejection audit paths when promotable is false.
        project_job = enqueue_project_memory_records_job(
            self._store,
            quality_report_id=result_json["quality_report_id"],
            session_id=result_json["session_id"],
            quality_job_id=job.id,
        )
        promote_job = enqueue_promote_durable_memory_job(
            self._store,
            quality_report_id=result_json["quality_report_id"],
            session_id=result_json["session_id"],
            quality_job_id=job.id,
        )
        result_json["project_memory_records_job_id"] = project_job.id
        result_json["promote_durable_memory_job_id"] = promote_job.id
        return result_json

    def _project_memory_records(self, job: Job) -> dict[str, Any]:
        scope = _payload_memory_projection_scope(job.payload_json)
        self._database.initialize()
        if scope == "quality_report":
            return self._project_quality_report_memory_records(job)
        return self._rebuild_memory_projection()

    def _project_quality_report_memory_records(self, job: Job) -> dict[str, Any]:
        quality_report_id = _payload_quality_report_id(job.payload_json)
        with self._database.session() as session:
            result = project_session_claims(session, quality_report_id, self._memory_projection())
            result_json = {
                "status": "completed",
                "scope": "quality_report",
                "quality_report_id": result.report_id,
                "snapshot_id": result.snapshot_id,
                "eligible": result.eligible,
                "indexed_count": result.indexed_count,
                "skipped_count": result.skipped_count,
                "deleted_count": result.deleted_count,
                "failed_count": result.failed_count,
                "reason": result.reason,
            }
        if result.failed_count > 0:
            raise MemoryProjectionJobError()
        return result_json

    def _rebuild_memory_projection(self) -> dict[str, Any]:
        durable_error: DurableMemoryProjectionError | None = None
        durable_failed_count = 0
        with self._database.session() as session:
            projection = self._memory_projection()
            reports = list(
                session.scalars(
                    select(SessionInterpretationQualityReport).order_by(SessionInterpretationQualityReport.id)
                ),
            )
            durable_memories = list(session.scalars(select(DurableMemoryItem).order_by(DurableMemoryItem.id)))
            report_results = [project_session_claims(session, report.id, projection) for report in reports]
            durable_records: list[MemoryProjectionRecord] = []
            for memory in durable_memories:
                record, error = _project_durable_memory_record_outcome(session, memory, projection)
                if record is not None:
                    durable_records.append(record)
                    continue
                durable_failed_count += 1
                if durable_error is None:
                    durable_error = error
            result_json = {
                "status": "completed",
                "scope": "all",
                "quality_report_count": len(report_results),
                "durable_memory_count": len(durable_records) + durable_failed_count,
                "indexed_count": sum(result.indexed_count for result in report_results)
                + _indexed_projection_record_count(durable_records),
                "skipped_count": sum(result.skipped_count for result in report_results),
                "deleted_count": sum(result.deleted_count for result in report_results)
                + _deleted_projection_record_count(durable_records),
                "failed_count": sum(result.failed_count for result in report_results) + durable_failed_count,
            }
        if durable_error is not None:
            raise durable_error
        if result_json["failed_count"] > 0:
            raise MemoryProjectionJobError()
        return result_json

    def _promote_durable_memory(self, job: Job) -> dict[str, Any]:
        quality_report_id = _payload_quality_report_id(job.payload_json)
        self._database.initialize()
        counts = {
            DURABLE_MEMORY_STATUS_PROMOTED: 0,
            DURABLE_MEMORY_STATUS_REJECTED: 0,
            DURABLE_MEMORY_STATUS_QUARANTINED: 0,
            DURABLE_MEMORY_STATUS_ARCHIVED: 0,
        }
        skipped_packet_count = 0
        failed_packet_count = 0
        processed_count = 0
        with self._database.session() as session:
            report = session.get(SessionInterpretationQualityReport, quality_report_id)
            if report is None:
                return {
                    "status": "completed",
                    "quality_report_id": quality_report_id,
                    "claim_count": 0,
                    "processed_count": 0,
                    "skipped_packet_count": 0,
                    "failed_packet_count": 1,
                    "final_status_counts": counts,
                    "reason": "report_not_found",
                }
            claim_count = _quality_report_claim_count(report)
            for claim_index in range(claim_count):
                try:
                    outcome = self._promote_quality_report_claim(session, job, quality_report_id, claim_index)
                except DurableMemoryPacketError:
                    failed_packet_count += 1
                    continue
                if outcome == "skipped":
                    skipped_packet_count += 1
                    continue
                processed_count += 1
                counts[outcome] = counts.get(outcome, 0) + 1

        return {
            "status": "completed",
            "quality_report_id": quality_report_id,
            "claim_count": claim_count,
            "processed_count": processed_count,
            "skipped_packet_count": skipped_packet_count,
            "failed_packet_count": failed_packet_count,
            "final_status_counts": counts,
        }

    def _promote_quality_report_claim(
        self,
        session: Session,
        job: Job,
        quality_report_id: int,
        claim_index: int,
    ) -> str:
        packet = build_durable_memory_evidence_packet(session, quality_report_id, claim_index)
        memory, upsert_outcome = _upsert_durable_memory_candidate(session, packet, job.id)
        if upsert_outcome == "skipped":
            return "skipped"
        _replace_durable_memory_sources(session, memory, packet)
        if upsert_outcome == "created":
            _add_durable_memory_audit_event(
                session,
                memory,
                event_type="candidate_created",
                from_status=None,
                to_status=memory.status,
                reason_code="candidate_created",
                details={"quality_report_id": quality_report_id, "claim_index": claim_index},
            )
        _add_durable_memory_audit_event(
            session,
            memory,
            event_type="eligibility_evaluated",
            from_status=memory.status,
            to_status=memory.status,
            reason_code="eligible" if packet.eligibility.is_eligible else f"blocked_{packet.eligibility.block_reason}",
            details={"is_eligible": packet.eligibility.is_eligible, "block_reason": packet.eligibility.block_reason},
        )
        if not packet.eligibility.is_eligible:
            decision = self._durable_reducer.decide(ReducerContext(memory, packet.eligibility, None, None))
            persist_reducer_decision(session, memory, decision)
            project_durable_memory_record(session, memory, self._memory_projection())
            return memory.status

        evaluation_result = self._candidate_evaluator().evaluate(packet)
        preliminary_decision = self._durable_reducer.decide(
            ReducerContext(memory, packet.eligibility, evaluation_result.output, None),
        )
        if preliminary_decision.reason_code != "metrics_all_healthy":
            persist_reducer_decision(session, memory, preliminary_decision, evaluation_result=evaluation_result)
            project_durable_memory_record(session, memory, self._memory_projection())
            return memory.status

        relation_result = assess_durable_memory_relations(session, memory.id, self._memory_projection())
        _add_relation_assessed_audit_event(session, memory, relation_result)
        final_decision = self._durable_reducer.decide(
            ReducerContext(memory, packet.eligibility, evaluation_result.output, relation_result),
        )
        persist_reducer_decision(
            session,
            memory,
            final_decision,
            evaluation_result=evaluation_result,
            relation_result=relation_result,
        )
        project_durable_memory_record(session, memory, self._memory_projection())
        _project_archived_related_memory(session, memory, relation_result, self._memory_projection())
        return memory.status

    def _write_assessment_failed_quality_report(self, job: Job, *, error_type: str) -> None:
        try:
            snapshot_id = _payload_snapshot_id(job.payload_json)
        except InvalidJobPayloadError:
            return
        self._database.initialize()
        with self._database.session() as session:
            snapshot = session.get(SessionInterpretationSnapshot, snapshot_id)
            if snapshot is None:
                return
            deterministic = assess_deterministic_interpretation_quality(session, snapshot)
            draft = QualityReportDraft(
                quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
                quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
                derivation_status=deterministic.derivation_status,
                deterministic_status=deterministic.deterministic_status,
                semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
                promotable=False,
                deterministic_findings=list(deterministic.deterministic_findings),
                assessment_metadata={
                    **deterministic.assessment_metadata,
                    "assessment_failed_error_type": error_type,
                },
            )
            _replace_quality_report(session=session, job=job, snapshot=snapshot, draft=draft)

    def _session_interpreter(self) -> SessionInterpreter:
        if self._interpreter is not None:
            return self._interpreter
        return create_session_interpreter()

    def _tool_activity_summarizer(self) -> ToolActivitySummarizer:
        if self._tool_summarizer is not None:
            return self._tool_summarizer
        return create_tool_activity_summarizer()

    def _quality_assessor(self) -> QualityAssessor:
        if self._quality_assessor_adapter is not None:
            return self._quality_assessor_adapter
        return create_quality_assessor()

    def _memory_projection(self) -> MemoryProjection:
        if self._memory_projection_adapter is None:
            self._memory_projection_adapter = create_memory_projection()
        return self._memory_projection_adapter

    def _candidate_evaluator(self) -> CandidateEvaluator:
        if self._candidate_evaluator_adapter is None:
            self._candidate_evaluator_adapter = create_candidate_evaluator()
        return self._candidate_evaluator_adapter


async def _summarize_tool_activity_work(
    summarizer: ToolActivitySummarizer,
    work_items: tuple[ToolActivitySummaryWorkItem, ...],
    *,
    concurrency: int,
) -> list[ToolActivitySummaryOutcome]:
    outcomes: list[ToolActivitySummaryOutcome] = []
    for window in _tool_summary_windows(work_items, concurrency=concurrency):
        window_outcomes = await asyncio.gather(
            *(_summarize_tool_activity_work_item(summarizer, item) for item in window),
        )
        outcomes.extend(window_outcomes)
    return outcomes


def _tool_summary_windows(
    work_items: tuple[ToolActivitySummaryWorkItem, ...],
    *,
    concurrency: int,
) -> list[tuple[ToolActivitySummaryWorkItem, ...]]:
    return [work_items[index : index + concurrency] for index in range(0, len(work_items), concurrency)]


async def _summarize_tool_activity_work_item(
    summarizer: ToolActivitySummarizer,
    item: ToolActivitySummaryWorkItem,
) -> ToolActivitySummaryOutcome:
    try:
        return ToolActivitySummaryOutcome(
            activity_unit_id=item.activity_unit_id,
            result=await summarizer.summarize_async(item.summary_input),
        )
    except Exception as error:
        return ToolActivitySummaryOutcome(
            activity_unit_id=item.activity_unit_id,
            error_type=type(error).__name__,
        )


def _payload_transcript_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    transcript_id = payload.get("transcript_id")
    if not isinstance(transcript_id, int) or isinstance(transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)
    return transcript_id


def _payload_interpret_session(payload: Any) -> tuple[int, int | None, int | None]:
    transcript_id, analysis_run_id, process_job_id = _payload_analysis_job(payload)
    return transcript_id, analysis_run_id, process_job_id


def _payload_summarize_tool_activities(payload: Any) -> tuple[int, int, int | None]:
    transcript_id, analysis_run_id, process_job_id = _payload_analysis_job(payload)
    if analysis_run_id is None:
        raise InvalidJobPayloadError(ANALYSIS_RUN_ID_INTEGER_ERROR)
    return transcript_id, analysis_run_id, process_job_id


def _payload_snapshot_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    snapshot_id = payload.get("snapshot_id")
    if not isinstance(snapshot_id, int) or isinstance(snapshot_id, bool):
        raise InvalidJobPayloadError(SNAPSHOT_ID_INTEGER_ERROR)
    return snapshot_id


def _payload_quality_report_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    quality_report_id = payload.get("quality_report_id")
    if not isinstance(quality_report_id, int) or isinstance(quality_report_id, bool):
        raise InvalidJobPayloadError(QUALITY_REPORT_ID_INTEGER_ERROR)
    return quality_report_id


def _payload_memory_projection_scope(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    scope = payload.get("scope")
    if scope not in {"quality_report", "all"}:
        raise InvalidJobPayloadError(PROJECT_MEMORY_SCOPE_ERROR)
    return scope


def _payload_analysis_job(payload: Any) -> tuple[int, int | None, int | None]:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    transcript_id = payload.get("transcript_id")
    if not isinstance(transcript_id, int) or isinstance(transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)

    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None and (not isinstance(analysis_run_id, int) or isinstance(analysis_run_id, bool)):
        raise InvalidJobPayloadError(ANALYSIS_RUN_ID_INTEGER_ERROR)

    process_job_id = payload.get("process_job_id")
    if process_job_id is not None and (not isinstance(process_job_id, int) or isinstance(process_job_id, bool)):
        raise InvalidJobPayloadError(PROCESS_JOB_ID_INTEGER_ERROR)

    return transcript_id, analysis_run_id, process_job_id


def _tool_activity_summary_context(
    *,
    session: Session,
    transcript_id: int,
    analysis_run_id: int,
    process_job_id: int | None,
) -> ToolActivitySummaryContext | None:
    transcript = session.get(Transcript, transcript_id)
    if transcript is None:
        raise TranscriptNotFoundError(transcript_id)

    analysis_run = session.get(AnalysisRun, analysis_run_id)
    if (
        analysis_run is None
        or analysis_run.transcript_id != transcript_id
        or analysis_run.analysis_kind != ANALYSIS_KIND_TRANSCRIPT_STRUCTURE
        or analysis_run.status != ANALYSIS_STATUS_COMPLETED
        or _is_stale_analysis_run(session, transcript_id, analysis_run_id)
        or _is_stale_process_job(session, transcript_id, process_job_id)
    ):
        return None

    return ToolActivitySummaryContext(
        transcript_id=transcript.id,
        session_id=transcript.session.session_id,
        analysis_run_id=analysis_run.id,
        process_job_id=process_job_id,
        analyzed_through_entry_id=analysis_run.analyzed_through_entry_id,
        analyzed_through_byte_offset=analysis_run.analyzed_through_byte_offset,
        activity_count=analysis_run.activity_count,
        episode_count=analysis_run.episode_count,
        manifest_count=analysis_run.manifest_count,
        work_items=_tool_activity_summary_work_items(session, analysis_run.id),
    )


def _tool_activity_summary_work_items(
    session: Session,
    analysis_run_id: int,
) -> tuple[ToolActivitySummaryWorkItem, ...]:
    activities = list(
        session.scalars(
            select(ActivityUnit)
            .where(
                ActivityUnit.analysis_run_id == analysis_run_id,
                ActivityUnit.kind == ACTIVITY_KIND_TOOL_PAIR,
            )
            .order_by(ActivityUnit.ordinal, ActivityUnit.id),
        ),
    )
    entries = _transcript_entries_by_id(
        session,
        (entry_id for activity in activities for entry_id in activity.source_entry_ids_json),
    )
    return tuple(_tool_activity_summary_work_item(activity, entries) for activity in activities)


def _tool_activity_summary_work_item(
    activity: ActivityUnit,
    entries: dict[int, TranscriptEntry],
) -> ToolActivitySummaryWorkItem:
    source_entries = tuple(
        _tool_activity_source_entry(entries[entry_id])
        for entry_id in activity.source_entry_ids_json
        if entry_id in entries
    )
    return ToolActivitySummaryWorkItem(
        activity_unit_id=activity.id,
        summary_input=ToolActivitySummaryInput(
            activity_unit_id=activity.id,
            analysis_run_id=activity.analysis_run_id,
            ordinal=activity.ordinal,
            tool_call_id=activity.tool_call_id,
            tool_name=activity.tool_name,
            is_error=activity.is_error,
            source_entries=source_entries,
            receipt_metadata=activity.receipt_json,
        ),
    )


def _tool_activity_source_entry(entry: TranscriptEntry) -> ToolActivitySourceEntry:
    return ToolActivitySourceEntry(
        row_id=entry.id,
        entry_id=entry.entry_id,
        entry_type=entry.entry_type,
        message_role=entry.message_role,
        byte_start=entry.byte_start,
        byte_end=entry.byte_end,
        raw_line=entry.raw_line,
    )


def _transcript_entries_by_id(session: Session, entry_ids: Iterable[Any]) -> dict[int, TranscriptEntry]:
    row_ids = tuple(sorted({entry_id for entry_id in entry_ids if isinstance(entry_id, int)}))
    if not row_ids:
        return {}
    entries = session.scalars(select(TranscriptEntry).where(TranscriptEntry.id.in_(row_ids)))
    return {entry.id: entry for entry in entries if entry.id is not None}


def _apply_tool_summary_outcomes(session: Session, outcomes: list[ToolActivitySummaryOutcome]) -> None:
    if not outcomes:
        return

    activity_ids = [outcome.activity_unit_id for outcome in outcomes]
    activities = {
        activity.id: activity
        for activity in session.scalars(select(ActivityUnit).where(ActivityUnit.id.in_(activity_ids)))
    }
    for outcome in outcomes:
        activity = activities.get(outcome.activity_unit_id)
        if activity is None:
            continue
        if outcome.result is None:
            _mark_tool_summary_failed(activity, outcome)
        else:
            _mark_tool_summary_completed(activity, outcome.result)


def _mark_tool_summary_completed(activity: ActivityUnit, result: ToolActivitySummaryResult) -> None:
    activity.activity_text = _tool_activity_text(result)
    activity.activity_text_kind = ACTIVITY_TEXT_KIND_TOOL_SUMMARY
    activity.activity_text_status = ACTIVITY_TEXT_STATUS_COMPLETED
    activity.activity_text_metadata_json = {
        "version": 1,
        "producer": "tool_activity_summarizer",
        "prompt_version": result.prompt_version,
        "model_metadata": _safe_model_metadata(result.model_metadata),
        "summary_schema_version": result.model_metadata.get("schema_version"),
        "cited_source_entry_ids": list(result.output.cited_source_entry_ids),
    }


def _mark_tool_summary_failed(activity: ActivityUnit, outcome: ToolActivitySummaryOutcome) -> None:
    activity.activity_text = None
    activity.activity_text_kind = ACTIVITY_TEXT_KIND_UNAVAILABLE
    activity.activity_text_status = ACTIVITY_TEXT_STATUS_FAILED
    activity.activity_text_metadata_json = {
        "version": 1,
        "producer": "tool_activity_summarizer",
        "status": "failed",
        "error_type": outcome.error_type or "UnknownError",
    }


def _tool_activity_text(result: ToolActivitySummaryResult) -> str:
    output = result.output
    parts = [f"Tool summary:\n{output.summary}"]
    if output.outcome is not None:
        parts.append(f"Outcome: {output.outcome}")
    if output.key_details:
        details = "\n".join(f"- {detail}" for detail in output.key_details)
        parts.append(f"Key details:\n{details}")
    return "\n".join(parts)


def _tool_summary_result_json(
    context: ToolActivitySummaryContext,
    outcomes: list[ToolActivitySummaryOutcome],
) -> dict[str, Any]:
    failed_activity_unit_ids = [outcome.activity_unit_id for outcome in outcomes if outcome.result is None]
    return {
        "status": "completed",
        "transcript_id": context.transcript_id,
        "session_id": context.session_id,
        "analysis_run_id": context.analysis_run_id,
        "process_job_id": context.process_job_id,
        "tool_pair_activity_count": len(context.work_items),
        "summarized_activity_count": len(outcomes) - len(failed_activity_unit_ids),
        "failed_activity_count": len(failed_activity_unit_ids),
        "failed_activity_unit_ids": failed_activity_unit_ids,
    }


def _tool_summary_stale_result_json(
    *,
    transcript_id: int,
    analysis_run_id: int,
    process_job_id: int | None,
) -> dict[str, Any]:
    return {
        "status": "stale",
        "is_stale": True,
        "transcript_id": transcript_id,
        "analysis_run_id": analysis_run_id,
        "process_job_id": process_job_id,
        "interpret_session_job_id": None,
        "tool_pair_activity_count": 0,
        "summarized_activity_count": 0,
        "failed_activity_count": 0,
    }


def _is_stale_analysis_run(session: Session, transcript_id: int, analysis_run_id: int) -> bool:
    latest_run_id = session.scalar(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.transcript_id == transcript_id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1),
    )
    return latest_run_id != analysis_run_id


def _is_stale_process_job(session: Session, transcript_id: int, process_job_id: int | None) -> bool:
    if process_job_id is None:
        return False

    # Phase 5A rebuilds delete and recreate analysis rows; SQLite may reuse ids.
    # The process job id is the durable freshness token for auto-enqueued work.
    latest_run = session.scalar(
        select(AnalysisRun)
        .where(
            AnalysisRun.transcript_id == transcript_id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1),
    )
    return latest_run is None or latest_run.job_id != process_job_id


def _completed_episode_outcome(
    packet: InterpretationPacket,
    episode: EpisodePacket,
    validated: ValidatedInterpretation,
    interpreter_result: InterpretationResult,
) -> EpisodeInterpretationOutcome:
    return EpisodeInterpretationOutcome(
        episode=episode,
        packet=packet,
        status=EPISODE_INTERPRETATION_STATUS_COMPLETED,
        validated=validated,
        interpreter_result=interpreter_result,
    )


def _skipped_episode_outcome(
    packet: InterpretationPacket,
    episode: EpisodePacket,
) -> EpisodeInterpretationOutcome:
    return EpisodeInterpretationOutcome(
        episode=episode,
        packet=packet,
        status=EPISODE_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    )


def _skipped_episode_outcomes(packet: InterpretationPacket) -> tuple[EpisodeInterpretationOutcome, ...]:
    return tuple(
        _skipped_episode_outcome(build_episode_interpretation_packet(packet, episode), episode)
        for episode in packet.episode_packets
    )


def _failed_episode_outcome(
    packet: InterpretationPacket,
    episode: EpisodePacket,
    error: Exception,
) -> EpisodeInterpretationOutcome:
    return EpisodeInterpretationOutcome(
        episode=episode,
        packet=packet,
        status=EPISODE_INTERPRETATION_STATUS_FAILED,
        failure_metadata=_episode_failure_metadata(error),
        error=error,
    )


def _episode_failure_metadata(error: Exception) -> dict[str, Any]:
    metadata = EpisodeInterpretationFailureMetadata(
        error_type=type(error).__name__,
        safe_message=_safe_episode_error_message(error),
        cause_type=type(error.__cause__).__name__ if error.__cause__ is not None else None,
    )
    return metadata.model_dump(mode="json", exclude_none=True, exclude_defaults=True)


def _safe_episode_error_message(error: Exception) -> str | None:
    if isinstance(error, (InterpretationValidationError, InterpreterUnavailableError)):
        return str(error)
    if error.__class__.__module__.startswith("pi_memory."):
        return str(error)
    return None


def _replace_episode_interpretation_snapshots(
    *,
    session: Session,
    job: Job,
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> None:
    analysis_run_id = packet.readiness.latest_analysis_run_id
    if analysis_run_id is None:
        return

    session.execute(
        delete(EpisodeInterpretationSnapshot).where(
            EpisodeInterpretationSnapshot.analysis_run_id == analysis_run_id,
        ),
    )
    session.flush()
    for outcome in outcomes:
        session.add(_episode_interpretation_snapshot(job, outcome))
    session.flush()


def _episode_interpretation_snapshot(
    job: Job,
    outcome: EpisodeInterpretationOutcome,
) -> EpisodeInterpretationSnapshot:
    readiness = outcome.packet.readiness
    interpretation = outcome.validated
    result = outcome.interpreter_result
    return EpisodeInterpretationSnapshot(
        session_id=readiness.session_row_id,
        transcript_id=readiness.transcript_id,
        analysis_run_id=readiness.latest_analysis_run_id,
        episode_id=outcome.episode.episode_id,
        job_id=job.id,
        status=outcome.status,
        episode_ordinal=outcome.episode.ordinal,
        activity_count=outcome.episode.activity_count,
        claim_source_activity_count=outcome.episode.claim_source_activity_count,
        analyzed_through_entry_id=readiness.analyzed_through_entry_id,
        analyzed_through_byte_offset=readiness.analyzed_through_byte_offset,
        interpretation_json=dict(interpretation.interpretation_json) if interpretation is not None else {},
        citations_json=_episode_citations_json(interpretation),
        model_metadata_json=dict(result.model_metadata) if result is not None else {},
        failure_metadata_json=dict(outcome.failure_metadata or {}),
        prompt_version=result.prompt_version if result is not None else None,
        schema_version=INTERPRETATION_SCHEMA_VERSION,
    )


def _episode_citations_json(interpretation: ValidatedInterpretation | None) -> list[dict[str, Any]]:
    if interpretation is None:
        return []
    return [dict(citation) for citation in interpretation.citations_json]


def _aggregate_episode_interpretations(
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> tuple[ValidatedInterpretation, InterpretationResult]:
    completed = tuple(outcome for outcome in outcomes if outcome.validated is not None)
    first_result = _first_interpreter_result(completed)
    coverage = _episode_interpretation_coverage(packet, outcomes)
    output = InterpretationOutput(
        analysis_run_id=packet.readiness.latest_analysis_run_id or 0,
        analyzed_through_entry_id=packet.readiness.analyzed_through_entry_id,
        analyzed_through_byte_offset=packet.readiness.analyzed_through_byte_offset,
        goal=_aggregated_goal(packet),
        summary=_aggregated_summary(coverage),
        claims=[claim for outcome in completed for claim in outcome.validated.output.claims],
        open_questions=[question for outcome in completed for question in outcome.validated.output.open_questions],
        citations=[citation for outcome in completed for citation in outcome.validated.output.citations],
    )
    validated = validate_interpretation_output(output, packet)
    interpretation_json = dict(validated.interpretation_json)
    interpretation_json["aggregation"] = coverage.model_dump(mode="json")
    return (
        ValidatedInterpretation(
            output=validated.output,
            interpretation_json=interpretation_json,
            citations_json=validated.citations_json,
        ),
        InterpretationResult(
            output=validated.output,
            model_metadata=_aggregated_model_metadata(first_result.model_metadata, coverage),
            prompt_version=first_result.prompt_version,
        ),
    )


def _first_interpreter_result(outcomes: tuple[EpisodeInterpretationOutcome, ...]) -> InterpretationResult:
    for outcome in outcomes:
        if outcome.interpreter_result is not None:
            return outcome.interpreter_result
    raise InterpretationValidationError.empty_claims()


def _aggregated_goal(packet: InterpretationPacket) -> str:
    stable_session_id = packet.readiness.stable_session_id or "unknown session"
    return f"Interpret session {stable_session_id} from episode-level memory claims."


def _aggregated_summary(coverage: EpisodeInterpretationCoverage) -> str:
    return (
        "Episode-level interpretation extracted claims from "
        f"{coverage.completed_episode_count} of {coverage.claim_source_episode_count} "
        "claim-source episode(s)."
    )


def _aggregated_model_metadata(
    model_metadata: Mapping[str, Any],
    coverage: EpisodeInterpretationCoverage,
) -> dict[str, Any]:
    return {
        **dict(model_metadata),
        "aggregation_mode": coverage.aggregation_mode,
        "coverage_status": coverage.coverage_status,
        "completed_episode_count": coverage.completed_episode_count,
        "failed_episode_count": coverage.failed_episode_count,
        "skipped_episode_count": coverage.skipped_episode_count,
    }


def _episode_interpretation_coverage(
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> EpisodeInterpretationCoverage:
    claim_source_outcomes = tuple(outcome for outcome in outcomes if outcome.episode.claim_source_activity_count > 0)
    completed = tuple(outcome for outcome in outcomes if outcome.status == EPISODE_INTERPRETATION_STATUS_COMPLETED)
    skipped = tuple(
        outcome for outcome in outcomes if outcome.status == EPISODE_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES
    )
    failed = tuple(outcome for outcome in outcomes if outcome.status == EPISODE_INTERPRETATION_STATUS_FAILED)
    return EpisodeInterpretationCoverage(
        coverage_status=_episode_coverage_status(claim_source_outcomes, completed, failed),
        total_episode_count=len(packet.episode_packets),
        claim_source_episode_count=len(claim_source_outcomes),
        completed_episode_count=len(completed),
        skipped_episode_count=len(skipped),
        failed_episode_count=len(failed),
        total_claim_source_activity_count=packet.readiness.claim_source_activity_count,
        completed_claim_source_activity_count=sum(outcome.episode.claim_source_activity_count for outcome in completed),
        skipped_claim_source_activity_count=sum(outcome.episode.claim_source_activity_count for outcome in skipped),
        failed_claim_source_activity_count=sum(outcome.episode.claim_source_activity_count for outcome in failed),
    )


def _episode_coverage_status(
    claim_source_outcomes: tuple[EpisodeInterpretationOutcome, ...],
    completed: tuple[EpisodeInterpretationOutcome, ...],
    failed: tuple[EpisodeInterpretationOutcome, ...],
) -> str:
    if not claim_source_outcomes:
        return "skipped_no_claim_sources"
    if not failed and len(completed) == len(claim_source_outcomes):
        return "complete"
    return "partial"


def _completed_episode_outcome_count(outcomes: tuple[EpisodeInterpretationOutcome, ...]) -> int:
    return sum(1 for outcome in outcomes if outcome.status == EPISODE_INTERPRETATION_STATUS_COMPLETED)


def _all_episode_interpretations_failed_error(outcomes: tuple[EpisodeInterpretationOutcome, ...]) -> Exception:
    for outcome in outcomes:
        if outcome.error is not None:
            return outcome.error
    return InterpretationValidationError.empty_claims()


def _episode_failure_result_json(
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> dict[str, Any]:
    result = _readiness_result_json(packet.readiness)
    result.update(
        {
            "status": "failed",
            "snapshot_id": None,
            "episode_interpretation": _episode_interpretation_coverage(packet, outcomes).model_dump(mode="json"),
        },
    )
    return result


def _replace_interpretation_snapshot(
    *,
    session: Session,
    job: Job,
    transcript: Transcript,
    packet: InterpretationPacket,
    status: str,
    blocked_reason: str | None = None,
    interpretation: ValidatedInterpretation | None = None,
    interpreter_result: InterpretationResult | None = None,
) -> SessionInterpretationSnapshot:
    existing = session.scalar(
        select(SessionInterpretationSnapshot).where(
            SessionInterpretationSnapshot.session_id == transcript.session_id,
        ),
    )
    if existing is not None:
        session.delete(existing)
        session.flush()

    readiness = packet.readiness
    snapshot = SessionInterpretationSnapshot(
        session_id=transcript.session_id,
        transcript_id=transcript.id,
        analysis_run_id=readiness.latest_analysis_run_id,
        job_id=job.id,
        status=status,
        blocked_reason=blocked_reason,
        analyzed_through_entry_id=readiness.analyzed_through_entry_id,
        analyzed_through_byte_offset=readiness.analyzed_through_byte_offset,
        origin_counts_json=dict(readiness.origin_counts),
        claim_source_activity_count=readiness.claim_source_activity_count,
        interpretation_json=dict(interpretation.interpretation_json) if interpretation is not None else {},
        citations_json=[dict(citation) for citation in interpretation.citations_json]
        if interpretation is not None
        else [],
        model_metadata_json=dict(interpreter_result.model_metadata) if interpreter_result is not None else {},
        prompt_version=interpreter_result.prompt_version if interpreter_result is not None else None,
        schema_version=INTERPRETATION_SCHEMA_VERSION,
    )
    session.add(snapshot)
    session.flush()
    session.refresh(snapshot)
    return snapshot


def _replace_quality_report(
    *,
    session: Session,
    job: Job,
    snapshot: SessionInterpretationSnapshot,
    draft: QualityReportDraft,
) -> SessionInterpretationQualityReport:
    existing = session.scalar(
        select(SessionInterpretationQualityReport).where(
            SessionInterpretationQualityReport.snapshot_id == snapshot.id,
        ),
    )
    if existing is not None:
        session.delete(existing)
        session.flush()

    report = SessionInterpretationQualityReport(
        snapshot_id=snapshot.id,
        job_id=job.id,
        quality_status=draft.quality_status,
        quality_reason=draft.quality_reason,
        derivation_status=draft.derivation_status,
        deterministic_status=draft.deterministic_status,
        semantic_status=draft.semantic_status,
        promotable=draft.promotable,
        deterministic_findings_json=draft.deterministic_findings_json,
        semantic_findings_json=draft.semantic_findings_json,
        claim_assessments_json=draft.claim_assessments_json,
        missing_high_signal_items_json=draft.missing_high_signal_items_json,
        model_metadata_json=draft.model_metadata_json,
        assessment_metadata_json=draft.assessment_metadata_json,
        prompt_version=draft.prompt_version,
        schema_version=draft.schema_version,
    )
    session.add(report)
    session.flush()
    session.refresh(report)
    return report


def _quality_report_claim_count(report: SessionInterpretationQualityReport) -> int:
    claims = report.snapshot.interpretation_json.get("claims")
    if not isinstance(claims, list):
        return 0
    return sum(1 for claim in claims if isinstance(claim, Mapping))


def _upsert_durable_memory_candidate(
    session: Session,
    packet: DurableMemoryEvidencePacket,
    job_id: int,
) -> tuple[DurableMemoryItem, CandidateUpsertOutcome]:
    candidate = packet.candidate
    report = session.get_one(SessionInterpretationQualityReport, candidate.quality_report_id)
    memory = session.scalar(
        select(DurableMemoryItem).where(
            DurableMemoryItem.quality_report_id == candidate.quality_report_id,
            DurableMemoryItem.claim_index == candidate.claim_index,
        ),
    )
    outcome: CandidateUpsertOutcome = "updated"
    if memory is None:
        outcome = "created"
        memory = DurableMemoryItem(
            session_id=report.snapshot.session_id,
            transcript_id=report.snapshot.transcript_id,
            snapshot_id=candidate.snapshot_id,
            quality_report_id=candidate.quality_report_id,
            claim_index=candidate.claim_index,
            status=DURABLE_MEMORY_STATUS_CANDIDATE,
            claim_kind=candidate.claim_kind,
            statement=candidate.statement,
            confidence=candidate.confidence,
            content_hash=candidate.content_hash,
        )
        session.add(memory)
    elif memory.status in PROMOTION_TERMINAL_STATUSES and memory.content_hash == candidate.content_hash:
        return memory, "skipped"

    memory.session_id = report.snapshot.session_id
    memory.transcript_id = report.snapshot.transcript_id
    memory.snapshot_id = candidate.snapshot_id
    memory.quality_report_id = candidate.quality_report_id
    memory.job_id = job_id
    memory.status = DURABLE_MEMORY_STATUS_CANDIDATE
    memory.status_reason = None
    memory.archived_reason = None
    memory.superseded_by_id = None
    memory.claim_kind = candidate.claim_kind
    memory.statement = candidate.statement
    memory.confidence = candidate.confidence
    memory.content_hash = candidate.content_hash
    memory.metadata_json = {
        **dict(memory.metadata_json or {}),
        "source_ref_ids": list(candidate.source_ref_ids),
        "omitted_source_count": packet.omitted_source_count,
    }
    session.flush()
    session.refresh(memory)
    return memory, outcome


def _is_terminal_same_content(memory: DurableMemoryItem, packet: DurableMemoryEvidencePacket) -> bool:
    return memory.status in PROMOTION_TERMINAL_STATUSES and memory.content_hash == packet.candidate.content_hash


def _replace_durable_memory_sources(
    session: Session,
    memory: DurableMemoryItem,
    packet: DurableMemoryEvidencePacket,
) -> None:
    session.execute(delete(DurableMemorySource).where(DurableMemorySource.memory_id == memory.id))
    for evidence in packet.source_evidence:
        source_origin = evidence.source_origin if evidence.source_origin in SOURCE_ORIGINS else SOURCE_ORIGIN_UNKNOWN
        session.add(
            DurableMemorySource(
                memory_id=memory.id,
                snapshot_id=packet.snapshot_id,
                quality_report_id=packet.quality_report_id,
                activity_unit_id=evidence.activity_unit_id,
                claim_index=packet.candidate.claim_index,
                source_ref=evidence.source_ref_id,
                source_origin=source_origin,
                source_kind=DURABLE_MEMORY_SOURCE_KIND_CLAIM,
                metadata_json=_source_metadata_json(evidence),
            ),
        )
    session.flush()


def _source_metadata_json(evidence: Any) -> dict[str, Any]:
    return {
        "activity_kind": evidence.activity_kind,
        "activity_ordinal": evidence.activity_ordinal,
        "episode_ordinal": evidence.episode_ordinal,
        "citation_metadata": dict(evidence.citation_metadata),
    }


def _add_durable_memory_audit_event(
    session: Session,
    memory: DurableMemoryItem,
    *,
    event_type: str,
    from_status: str | None,
    to_status: str | None,
    reason_code: str,
    details: Mapping[str, Any],
) -> DurableMemoryAuditEvent:
    event = DurableMemoryAuditEvent(
        memory=memory,
        job_id=memory.job_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        reason_code=reason_code,
        details_json={key: _audit_detail_value(value) for key, value in details.items()},
    )
    session.add(event)
    return event


def _add_relation_assessed_audit_event(
    session: Session,
    memory: DurableMemoryItem,
    result: RelationAssessmentResult,
) -> None:
    _add_durable_memory_audit_event(
        session,
        memory,
        event_type="relation_assessed",
        from_status=memory.status,
        to_status=memory.status,
        reason_code=result.assessment.relation_type,
        details={
            "relation_type": result.assessment.relation_type,
            "related_memory_id": result.related_memory_id,
            "resolved_hit_count": result.resolved_hit_count,
            "distance": result.distance,
        },
    )


def _project_archived_related_memory(
    session: Session,
    memory: DurableMemoryItem,
    relation_result: RelationAssessmentResult,
    projection: MemoryProjection,
) -> None:
    related_memory_id = relation_result.related_memory_id
    if related_memory_id is None or related_memory_id == memory.id:
        return
    related = session.get(DurableMemoryItem, related_memory_id)
    if related is not None and related.status == DURABLE_MEMORY_STATUS_ARCHIVED:
        project_durable_memory_record(session, related, projection)


def _project_durable_memory_record_outcome(
    session: Session,
    memory: DurableMemoryItem,
    projection: MemoryProjection,
) -> tuple[MemoryProjectionRecord | None, DurableMemoryProjectionError | None]:
    try:
        return project_durable_memory_record(session, memory, projection), None
    except DurableMemoryProjectionError as error:
        return None, error


def _indexed_projection_record_count(records: list[MemoryProjectionRecord]) -> int:
    return sum(1 for record in records if record.status != MEMORY_PROJECTION_STATUS_DELETED)


def _deleted_projection_record_count(records: list[MemoryProjectionRecord]) -> int:
    return sum(1 for record in records if record.status == MEMORY_PROJECTION_STATUS_DELETED)


def _audit_detail_value(value: Any) -> str | int | float | bool | None:
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)[:400]


def _stale_result_json(packet: InterpretationPacket) -> dict[str, Any]:
    result = _readiness_result_json(packet.readiness)
    result["status"] = "stale"
    result["is_stale"] = True
    result["snapshot_id"] = None
    return result


def _snapshot_result_json(
    packet: InterpretationPacket,
    snapshot: SessionInterpretationSnapshot,
) -> dict[str, Any]:
    result = _readiness_result_json(packet.readiness)
    result.update(
        {
            "status": snapshot.status,
            "snapshot_id": snapshot.id,
            "blocked_reason": snapshot.blocked_reason,
            "prompt_version": snapshot.prompt_version,
            "schema_version": snapshot.schema_version,
            "model_metadata": _safe_model_metadata(snapshot.model_metadata_json),
        },
    )
    coverage = _snapshot_episode_interpretation_coverage(snapshot)
    if coverage is not None:
        result["episode_interpretation"] = coverage
    return result


def _snapshot_episode_interpretation_coverage(snapshot: SessionInterpretationSnapshot) -> Mapping[str, Any] | None:
    interpretation = snapshot.interpretation_json if isinstance(snapshot.interpretation_json, Mapping) else {}
    coverage = interpretation.get("aggregation")
    return coverage if isinstance(coverage, Mapping) else None


def _quality_report_result_json(
    snapshot: SessionInterpretationSnapshot,
    report: SessionInterpretationQualityReport,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "snapshot_id": snapshot.id,
        "quality_report_id": report.id,
        "session_id": snapshot.session.session_id,
        "session_row_id": snapshot.session_id,
        "transcript_id": snapshot.transcript_id,
        "analysis_run_id": snapshot.analysis_run_id,
        "quality_status": report.quality_status,
        "quality_reason": report.quality_reason,
        "derivation_status": report.derivation_status,
        "deterministic_status": report.deterministic_status,
        "semantic_status": report.semantic_status,
        "promotable": report.promotable,
        "prompt_version": report.prompt_version,
        "schema_version": report.schema_version,
        "model_metadata": _safe_model_metadata(report.model_metadata_json),
    }


def _is_final_quality_attempt(job: Job) -> bool:
    return job.kind == JOB_KIND_ASSESS_INTERPRETATION_QUALITY and job.attempts >= job.max_attempts


def _readiness_result_json(readiness: InterpretationReadiness) -> dict[str, Any]:
    return {
        "session_id": readiness.stable_session_id,
        "transcript_id": readiness.transcript_id,
        "analysis_run_id": readiness.latest_analysis_run_id,
        "latest_analysis_run_id": readiness.latest_analysis_run_id,
        "requested_analysis_run_id": readiness.requested_analysis_run_id,
        "is_stale": readiness.is_stale,
        "blocked_reason": readiness.blocked_reason,
        "analyzed_through_entry_id": readiness.analyzed_through_entry_id,
        "analyzed_through_byte_offset": readiness.analyzed_through_byte_offset,
        "origin_counts": dict(readiness.origin_counts),
        "claim_source_activity_count": readiness.claim_source_activity_count,
        "activity_count": readiness.activity_count,
        "episode_count": readiness.episode_count,
        "manifest_count": readiness.manifest_count,
    }


def _safe_model_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in ("provider", "model", "mode") if key in metadata}
