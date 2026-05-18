"""Minimal pi-memory job runner."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
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
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    ActivityUnit,
    AnalysisRun,
    Database,
    Job,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
    database,
)
from pi_memory.interpretation import (
    INTERPRETATION_SCHEMA_VERSION,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
    SessionInterpreter,
    ToolActivitySourceEntry,
    ToolActivitySummarizer,
    ToolActivitySummaryInput,
    ToolActivitySummaryResult,
    ValidatedInterpretation,
    build_interpretation_packet,
    create_session_interpreter,
    create_tool_activity_summarizer,
    validate_interpretation_output,
)
from pi_memory.interpretation.packets import InterpretationPacket, InterpretationReadiness
from pi_memory.jobs.interpretation import (
    enqueue_assess_interpretation_quality_job,
    enqueue_interpret_session_job_for_analysis,
    enqueue_summarize_tool_activities_job,
)
from pi_memory.jobs.store import JobStore
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


class JobRunner:
    """Run a claimed durable job to completion or recorded failure."""

    def __init__(
        self,
        database: Database = database,
        interpreter: SessionInterpreter | None = None,
        tool_summarizer: ToolActivitySummarizer | None = None,
        quality_assessor: QualityAssessor | None = None,
    ) -> None:
        self._database = database
        self._store = JobStore(database=database)
        self._interpreter = interpreter
        self._tool_summarizer = tool_summarizer
        self._quality_assessor_adapter = quality_assessor

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
            elif packet.readiness.should_skip_model:
                snapshot = _replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
                )
                result_json = _snapshot_result_json(packet, snapshot)
            else:
                interpreter = self._session_interpreter()
                result = interpreter.interpret(packet)
                validated = validate_interpretation_output(result.output, packet)
                snapshot = _replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                    interpretation=validated,
                    interpreter_result=result,
                )
                result_json = _snapshot_result_json(packet, snapshot)
            snapshot_id = snapshot.id
            stable_session_id = packet.readiness.stable_session_id

        quality_job = enqueue_assess_interpretation_quality_job(
            self._store,
            snapshot_id=snapshot_id,
            session_id=stable_session_id,
            interpretation_job_id=job.id,
        )
        result_json["assess_interpretation_quality_job_id"] = quality_job.id
        return result_json

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
            return _quality_report_result_json(snapshot, report)

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
    return result


def _quality_report_result_json(
    snapshot: SessionInterpretationSnapshot,
    report: SessionInterpretationQualityReport,
) -> dict[str, Any]:
    return {
        "status": "completed",
        "snapshot_id": snapshot.id,
        "quality_report_id": report.id,
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
