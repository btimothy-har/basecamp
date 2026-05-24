"""Session interpretation pipeline stage."""

from __future__ import annotations

from typing import Any

from pi_memory.constants import (
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
)
from pi_memory.db.models import (
    Job,
    Transcript,
)
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.interpretation import (
    InterpretationValidationError,
    InterpreterUnavailableError,
    build_episode_interpretation_packet,
    build_interpretation_packet,
    validate_episode_interpretation_output,
)
from pi_memory.interpretation.packets import InterpretationPacket
from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.runtime.errors import (
    PermanentInterpretationValidationError,
    PermanentInterpreterUnavailableError,
    TranscriptNotFoundError,
)
from pi_memory.pipeline.stages.assess_interpretation_quality.enqueue import enqueue_assess_interpretation_quality_job
from pi_memory.pipeline.stages.interpret_session.snapshots import (
    EpisodeInterpretationOutcome,
    aggregate_episode_interpretations,
    all_episode_interpretations_failed_error,
    completed_episode_outcome,
    completed_episode_outcome_count,
    current_interpretation_snapshot_for_job,
    episode_failure_result_json,
    failed_episode_outcome,
    replace_episode_interpretation_snapshots,
    replace_interpretation_snapshot,
    skipped_episode_outcome,
    skipped_episode_outcomes,
    snapshot_result_json,
    stale_result_json,
)
from pi_memory.pipeline.utils import payloads
from pi_memory.pipeline.utils.freshness import is_stale_process_job


class InterpretSessionJob:
    """Interpret a transcript analysis into session memory claims."""

    kind = JOB_KIND_INTERPRET_SESSION

    def __init__(self, adapters: PipelineAdapters) -> None:
        self._adapters = adapters

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        try:
            return self._run(context, job)
        except InterpretationValidationError as error:
            raise PermanentInterpretationValidationError(str(error)) from error
        except InterpreterUnavailableError as error:
            raise PermanentInterpreterUnavailableError(str(error)) from error

    def _run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        transcript_id, analysis_run_id, process_job_id = payloads.interpret_session(job.payload_json)
        context.database.initialize()
        packet_for_model: InterpretationPacket | None = None
        snapshot_id: int | None = None
        stable_session_id = ""
        result_json: dict[str, Any] = {}
        with context.database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            packet = build_interpretation_packet(session, transcript, analysis_run_id=analysis_run_id)
            if packet.readiness.is_stale or is_stale_process_job(session, transcript_id, process_job_id):
                return stale_result_json(packet)

            existing_snapshot = current_interpretation_snapshot_for_job(
                session=session,
                job=job,
                transcript=transcript,
                packet=packet,
            )
            if existing_snapshot is not None:
                result_json = snapshot_result_json(packet, existing_snapshot)
                snapshot_id = existing_snapshot.id
                stable_session_id = packet.readiness.stable_session_id
            elif packet.readiness.blocked_reason is not None:
                snapshot = replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_BLOCKED,
                    blocked_reason=packet.readiness.blocked_reason,
                )
                result_json = snapshot_result_json(packet, snapshot)
                snapshot_id = snapshot.id
                stable_session_id = packet.readiness.stable_session_id
            elif packet.readiness.should_skip_model:
                outcomes = skipped_episode_outcomes(packet)
                replace_episode_interpretation_snapshots(
                    session=session,
                    job=job,
                    packet=packet,
                    outcomes=outcomes,
                )
                snapshot = replace_interpretation_snapshot(
                    session=session,
                    job=job,
                    transcript=transcript,
                    packet=packet,
                    status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
                )
                result_json = snapshot_result_json(packet, snapshot)
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
            with context.database.session() as session:
                transcript = session.get(Transcript, transcript_id)
                if transcript is None:
                    raise TranscriptNotFoundError(transcript_id)

                packet = build_interpretation_packet(session, transcript, analysis_run_id=analysis_run_id)
                if packet.readiness.is_stale or is_stale_process_job(session, transcript_id, process_job_id):
                    return stale_result_json(packet)

                replace_episode_interpretation_snapshots(
                    session=session,
                    job=job,
                    packet=packet,
                    outcomes=outcomes,
                )
                if completed_episode_outcome_count(outcomes) == 0:
                    failure_error = all_episode_interpretations_failed_error(outcomes)
                    snapshot_id = None
                    stable_session_id = packet.readiness.stable_session_id
                    result_json = episode_failure_result_json(packet, outcomes)
                else:
                    interpretation, interpreter_result = aggregate_episode_interpretations(packet, outcomes)
                    snapshot = replace_interpretation_snapshot(
                        session=session,
                        job=job,
                        transcript=transcript,
                        packet=packet,
                        status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                        interpretation=interpretation,
                        interpreter_result=interpreter_result,
                    )
                    result_json = snapshot_result_json(packet, snapshot)
                    snapshot_id = snapshot.id
                    stable_session_id = packet.readiness.stable_session_id
            if failure_error is not None:
                raise failure_error

        if snapshot_id is None:
            return result_json

        quality_job = enqueue_assess_interpretation_quality_job(
            context.store,
            snapshot_id=snapshot_id,
            session_id=stable_session_id,
            interpretation_job_id=job.id,
            idempotency_key=_assess_interpretation_quality_idempotency_key(snapshot_id),
        )
        result_json["assess_interpretation_quality_job_id"] = quality_job.id
        return result_json

    def _interpret_episode_outcomes(self, packet: InterpretationPacket) -> tuple[EpisodeInterpretationOutcome, ...]:
        interpreter = self._adapters.session_interpreter()
        outcomes: list[EpisodeInterpretationOutcome] = []
        for episode in packet.episode_packets:
            episode_packet = build_episode_interpretation_packet(packet, episode)
            if episode.claim_source_activity_count == 0:
                outcomes.append(skipped_episode_outcome(episode_packet, episode))
                continue
            try:
                result = interpreter.interpret(episode_packet)
                validated = validate_episode_interpretation_output(result.output, packet, episode)
            except Exception as error:
                outcomes.append(failed_episode_outcome(episode_packet, episode, error))
            else:
                outcomes.append(completed_episode_outcome(episode_packet, episode, validated, result))
        return tuple(outcomes)


def _assess_interpretation_quality_idempotency_key(snapshot_id: int) -> str:
    return f"{JOB_KIND_ASSESS_INTERPRETATION_QUALITY}:{JOB_KIND_INTERPRET_SESSION}:{snapshot_id}"
