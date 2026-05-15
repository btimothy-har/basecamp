"""Minimal pi-memory job runner."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.analysis import analyze_transcript_structure
from pi_memory.db import (
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    Database,
    Job,
    SessionInterpretationSnapshot,
    Transcript,
    database,
)
from pi_memory.interpretation import (
    INTERPRETATION_SCHEMA_VERSION,
    DeterministicSessionInterpreter,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
    SessionInterpreter,
    ValidatedInterpretation,
    build_interpretation_packet,
    validate_interpretation_output,
)
from pi_memory.interpretation.packets import InterpretationPacket, InterpretationReadiness
from pi_memory.jobs.store import JobStore
from pi_memory.recall import index_transcript

EXPECTED_OBJECT_PAYLOAD_ERROR = "expected object payload"
TRANSCRIPT_ID_INTEGER_ERROR = "transcript_id must be an integer"
ANALYSIS_RUN_ID_INTEGER_ERROR = "analysis_run_id must be an integer"


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
    """Raised when a process_transcript job references a missing transcript."""

    def __init__(self, transcript_id: int) -> None:
        super().__init__(f"Transcript {transcript_id} was not found")


class JobRunner:
    """Run a claimed durable job to completion or recorded failure."""

    def __init__(
        self,
        database: Database = database,
        interpreter: SessionInterpreter | None = None,
    ) -> None:
        self._database = database
        self._store = JobStore(database=database)
        self._interpreter = interpreter if interpreter is not None else DeterministicSessionInterpreter()

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
            self._store.fail(job_id, run_id, error=str(error), exit_code=1, retry=True, now=now)
            raise

        return self._store.complete(job_id, run_id, result_json=result_json, exit_code=0, now=now)

    def _dispatch(self, job: Job) -> dict[str, Any]:
        if job.kind == JOB_KIND_PROCESS_TRANSCRIPT:
            return self._process_transcript(job)
        if job.kind == JOB_KIND_INTERPRET_SESSION:
            return self._interpret_session(job)
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
            return {
                "transcript_id": transcript.id,
                "session_id": transcript.session.session_id,
                "entry_count": index_result.total_entries,
                "cursor_offset": transcript.cursor_offset,
                "file_size": transcript.file_size,
                "indexed_entry_count": index_result.indexed_entries,
                "phase_5a": analysis_result.to_result_json(),
            }

    def _interpret_session(self, job: Job) -> dict[str, Any]:
        transcript_id, analysis_run_id = _payload_interpret_session(job.payload_json)
        self._database.initialize()
        with self._database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            packet = build_interpretation_packet(session, transcript, analysis_run_id=analysis_run_id)
            if packet.readiness.is_stale:
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
                return _snapshot_result_json(packet, snapshot)

            if packet.readiness.should_skip_model:
                snapshot = _replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
                )
                return _snapshot_result_json(packet, snapshot)

            result = self._interpreter.interpret(packet)
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
            return _snapshot_result_json(packet, snapshot)


def _payload_transcript_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    transcript_id = payload.get("transcript_id")
    if not isinstance(transcript_id, int) or isinstance(transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)
    return transcript_id


def _payload_interpret_session(payload: Any) -> tuple[int, int | None]:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    transcript_id = payload.get("transcript_id")
    if not isinstance(transcript_id, int) or isinstance(transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)

    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None and (
        not isinstance(analysis_run_id, int) or isinstance(analysis_run_id, bool)
    ):
        raise InvalidJobPayloadError(ANALYSIS_RUN_ID_INTEGER_ERROR)

    return transcript_id, analysis_run_id


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


def _stale_result_json(packet: InterpretationPacket) -> dict[str, Any]:
    result = _readiness_result_json(packet.readiness)
    result["status"] = "stale"
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
    return {
        key: metadata[key]
        for key in ("provider", "model", "mode")
        if key in metadata
    }
