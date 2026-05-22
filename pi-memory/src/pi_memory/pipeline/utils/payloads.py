"""Payload helpers for memory pipeline jobs."""

from __future__ import annotations

from typing import Any

from pi_memory.pipeline.runtime.errors import InvalidJobPayloadError

EXPECTED_OBJECT_PAYLOAD_ERROR = "expected object payload"
TRANSCRIPT_ID_INTEGER_ERROR = "transcript_id must be an integer"
ANALYSIS_RUN_ID_INTEGER_ERROR = "analysis_run_id must be an integer"
PROCESS_JOB_ID_INTEGER_ERROR = "process_job_id must be an integer"
SNAPSHOT_ID_INTEGER_ERROR = "snapshot_id must be an integer"
QUALITY_REPORT_ID_INTEGER_ERROR = "quality_report_id must be an integer"
PROJECT_MEMORY_SCOPE_ERROR = "memory projection scope must be 'quality_report' or 'all'"


def transcript_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    value = payload.get("transcript_id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)
    return value


def interpret_session(payload: Any) -> tuple[int, int | None, int | None]:
    return analysis_job(payload)


def summarize_tool_activities(payload: Any) -> tuple[int, int, int | None]:
    parsed_transcript_id, analysis_run_id, process_job_id = analysis_job(payload)
    if analysis_run_id is None:
        raise InvalidJobPayloadError(ANALYSIS_RUN_ID_INTEGER_ERROR)
    return parsed_transcript_id, analysis_run_id, process_job_id


def snapshot_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    value = payload.get("snapshot_id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidJobPayloadError(SNAPSHOT_ID_INTEGER_ERROR)
    return value


def quality_report_id(payload: Any) -> int:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    value = payload.get("quality_report_id")
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidJobPayloadError(QUALITY_REPORT_ID_INTEGER_ERROR)
    return value


def memory_projection_scope(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    scope = payload.get("scope")
    if scope not in {"quality_report", "all"}:
        raise InvalidJobPayloadError(PROJECT_MEMORY_SCOPE_ERROR)
    return scope


def analysis_job(payload: Any) -> tuple[int, int | None, int | None]:
    if not isinstance(payload, dict):
        raise InvalidJobPayloadError(EXPECTED_OBJECT_PAYLOAD_ERROR)

    parsed_transcript_id = payload.get("transcript_id")
    if not isinstance(parsed_transcript_id, int) or isinstance(parsed_transcript_id, bool):
        raise InvalidJobPayloadError(TRANSCRIPT_ID_INTEGER_ERROR)

    analysis_run_id = payload.get("analysis_run_id")
    if analysis_run_id is not None and (not isinstance(analysis_run_id, int) or isinstance(analysis_run_id, bool)):
        raise InvalidJobPayloadError(ANALYSIS_RUN_ID_INTEGER_ERROR)

    process_job_id = payload.get("process_job_id")
    if process_job_id is not None and (not isinstance(process_job_id, int) or isinstance(process_job_id, bool)):
        raise InvalidJobPayloadError(PROCESS_JOB_ID_INTEGER_ERROR)

    return parsed_transcript_id, analysis_run_id, process_job_id


def analysis_job_payload(
    *,
    transcript_id: int,
    session_id: str,
    analysis_run_id: int,
    process_job_id: int | None,
    analyzed_through_entry_id: int | None,
    analyzed_through_byte_offset: int,
    activity_count: int,
    episode_count: int,
    manifest_count: int,
) -> dict[str, object]:
    return {
        "transcript_id": transcript_id,
        "analysis_run_id": analysis_run_id,
        # Remaining fields are audit/debug context for inspecting queued work.
        # Runners use SQLite as truth and only require ids/freshness tokens.
        "session_id": session_id,
        "process_job_id": process_job_id,
        "analyzed_through_entry_id": analyzed_through_entry_id,
        "analyzed_through_byte_offset": analyzed_through_byte_offset,
        "activity_count": activity_count,
        "episode_count": episode_count,
        "manifest_count": manifest_count,
    }
