"""Interpretation snapshot persistence helpers for the memory pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from pi_memory.db import (
    EPISODE_INTERPRETATION_STATUS_COMPLETED,
    EPISODE_INTERPRETATION_STATUS_FAILED,
    EPISODE_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    EpisodeInterpretationSnapshot,
    Job,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.interpretation import (
    INTERPRETATION_SCHEMA_VERSION,
    EpisodeInterpretationCoverage,
    EpisodeInterpretationFailureMetadata,
    InterpretationOutput,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
    ValidatedInterpretation,
    build_episode_interpretation_packet,
    validate_interpretation_output,
)
from pi_memory.interpretation.packets import EpisodePacket, InterpretationPacket, InterpretationReadiness
from pi_memory.pipeline.model_metadata import safe_model_metadata


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


def completed_episode_outcome(
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


def skipped_episode_outcome(
    packet: InterpretationPacket,
    episode: EpisodePacket,
) -> EpisodeInterpretationOutcome:
    return EpisodeInterpretationOutcome(
        episode=episode,
        packet=packet,
        status=EPISODE_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    )


def skipped_episode_outcomes(packet: InterpretationPacket) -> tuple[EpisodeInterpretationOutcome, ...]:
    return tuple(
        skipped_episode_outcome(build_episode_interpretation_packet(packet, episode), episode)
        for episode in packet.episode_packets
    )


def failed_episode_outcome(
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


def replace_episode_interpretation_snapshots(
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


def aggregate_episode_interpretations(
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


def episode_interpretation_coverage(
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> EpisodeInterpretationCoverage:
    return _episode_interpretation_coverage(packet, outcomes)


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


def completed_episode_outcome_count(outcomes: tuple[EpisodeInterpretationOutcome, ...]) -> int:
    return sum(1 for outcome in outcomes if outcome.status == EPISODE_INTERPRETATION_STATUS_COMPLETED)


def all_episode_interpretations_failed_error(outcomes: tuple[EpisodeInterpretationOutcome, ...]) -> Exception:
    for outcome in outcomes:
        if outcome.error is not None:
            return outcome.error
    return InterpretationValidationError.empty_claims()


def episode_failure_result_json(
    packet: InterpretationPacket,
    outcomes: tuple[EpisodeInterpretationOutcome, ...],
) -> dict[str, Any]:
    result = readiness_result_json(packet.readiness)
    result.update(
        {
            "status": "failed",
            "snapshot_id": None,
            "episode_interpretation": _episode_interpretation_coverage(packet, outcomes).model_dump(mode="json"),
        },
    )
    return result


def replace_interpretation_snapshot(
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


def stale_result_json(packet: InterpretationPacket) -> dict[str, Any]:
    result = readiness_result_json(packet.readiness)
    result["status"] = "stale"
    result["is_stale"] = True
    result["snapshot_id"] = None
    return result


def snapshot_result_json(
    packet: InterpretationPacket,
    snapshot: SessionInterpretationSnapshot,
) -> dict[str, Any]:
    result = readiness_result_json(packet.readiness)
    result.update(
        {
            "status": snapshot.status,
            "snapshot_id": snapshot.id,
            "blocked_reason": snapshot.blocked_reason,
            "prompt_version": snapshot.prompt_version,
            "schema_version": snapshot.schema_version,
            "model_metadata": safe_model_metadata(snapshot.model_metadata_json),
        },
    )
    coverage = snapshot_episode_interpretation_coverage(snapshot)
    if coverage is not None:
        result["episode_interpretation"] = coverage
    return result


def snapshot_episode_interpretation_coverage(snapshot: SessionInterpretationSnapshot) -> Mapping[str, Any] | None:
    interpretation = snapshot.interpretation_json if isinstance(snapshot.interpretation_json, Mapping) else {}
    coverage = interpretation.get("aggregation")
    return coverage if isinstance(coverage, Mapping) else None


def readiness_result_json(readiness: InterpretationReadiness) -> dict[str, Any]:
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
