"""Freshness checks for analysis-derived pipeline jobs."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.constants import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
)
from pi_memory.db.models import AnalysisRun


def is_stale_analysis_run(session: Session, transcript_id: int, analysis_run_id: int) -> bool:
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


def is_stale_process_job(session: Session, transcript_id: int, process_job_id: int | None) -> bool:
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
