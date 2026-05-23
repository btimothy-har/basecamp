"""Tool activity summarization helpers for the memory pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.db.constants import (
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_TEXT_KIND_TOOL_SUMMARY,
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ACTIVITY_TEXT_STATUS_FAILED,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
)
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation import (
    ToolActivitySourceEntry,
    ToolActivitySummarizer,
    ToolActivitySummaryInput,
    ToolActivitySummaryResult,
)
from pi_memory.pipeline.runtime.errors import TranscriptNotFoundError
from pi_memory.pipeline.utils.freshness import is_stale_analysis_run, is_stale_process_job
from pi_memory.pipeline.utils.metadata import safe_model_metadata
from pi_memory.settings import settings as memory_settings


@dataclass(frozen=True)
class ToolActivitySummaryWorkItem:
    """Tool-pair activity input prepared outside a DB transaction."""

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
    """Safe context needed to summarize tool activities."""

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


def summarize_tool_activity_work(
    summarizer: ToolActivitySummarizer,
    work_items: tuple[ToolActivitySummaryWorkItem, ...],
) -> list[ToolActivitySummaryOutcome]:
    if not work_items:
        return []

    return asyncio.run(
        _summarize_tool_activity_work(
            summarizer,
            work_items,
            concurrency=memory_settings.tool_summary_concurrency,
        ),
    )


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


def tool_activity_summary_context(
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
        or is_stale_analysis_run(session, transcript_id, analysis_run_id)
        or is_stale_process_job(session, transcript_id, process_job_id)
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


def apply_tool_summary_outcomes(session: Session, outcomes: list[ToolActivitySummaryOutcome]) -> None:
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
        "model_metadata": safe_model_metadata(result.model_metadata),
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


def tool_summary_result_json(
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


def tool_summary_stale_result_json(
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
