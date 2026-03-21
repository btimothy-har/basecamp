"""Read-only query layer for the visualization dashboard.

Builds on existing domain models and the Database singleton. Never mutates
data — safe for concurrent access with the daemon via WAL mode.
"""

from __future__ import annotations

from sqlalchemy import func

from observer.data.enums import RawEventStatus, SectionType
from observer.data.schemas import (
    ProjectSchema,
    RawEventSchema,
    TranscriptExtractionSchema,
    TranscriptSchema,
)
from observer.services.db import Database


def _scoped_transcript_ids(
    session,
    project_id: int | None,
    worktree_id: int | None | str,
):
    """Subquery returning transcript IDs matching the given scope."""
    q = session.query(TranscriptSchema.id)
    if project_id is not None:
        q = q.filter(TranscriptSchema.project_id == project_id)
    if worktree_id == "main":
        q = q.filter(TranscriptSchema.worktree_id.is_(None))
    elif isinstance(worktree_id, int):
        q = q.filter(TranscriptSchema.worktree_id == worktree_id)
    return q.subquery()


# -- Aggregate stats --


def get_pipeline_stats(
    transcript_id: int | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> dict:
    """Top-level counts for the pipeline overview."""
    with Database().session() as session:
        events_q = session.query(RawEventSchema)
        extractions_q = session.query(TranscriptExtractionSchema)

        if transcript_id is not None:
            events_q = events_q.filter(RawEventSchema.transcript_id == transcript_id)
            extractions_q = extractions_q.filter(TranscriptExtractionSchema.transcript_id == transcript_id)
        elif project_id is not None:
            tid_sq = _scoped_transcript_ids(session, project_id, worktree_id)
            events_q = events_q.filter(RawEventSchema.transcript_id.in_(tid_sq))
            extractions_q = extractions_q.filter(TranscriptExtractionSchema.transcript_id.in_(tid_sq))

        total_events = events_q.count()
        processed = events_q.filter(RawEventSchema.processed == RawEventStatus.PROCESSED).count()
        skipped = events_q.filter(RawEventSchema.processed == RawEventStatus.SKIPPED).count()
        errors = events_q.filter(RawEventSchema.processed == RawEventStatus.ERROR).count()
        pending = events_q.filter(RawEventSchema.processed == RawEventStatus.PENDING).count()

        return {
            "total_events": total_events,
            "processed": processed,
            "skipped": skipped,
            "errors": errors,
            "pending": pending,
            "total_extractions": extractions_q.count(),
        }


def get_processing_status_counts(
    transcript_id: int | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Event counts grouped by processing status."""
    labels = {s: s.name.lower() for s in RawEventStatus}
    with Database().session() as session:
        q = session.query(RawEventSchema.processed, func.count(RawEventSchema.id)).group_by(RawEventSchema.processed)

        if transcript_id is not None:
            q = q.filter(RawEventSchema.transcript_id == transcript_id)
        elif project_id is not None:
            q = q.filter(RawEventSchema.transcript_id.in_(_scoped_transcript_ids(session, project_id, worktree_id)))

        return [{"status": labels.get(status, str(status)), "count": count} for status, count in q.all()]


def get_section_type_counts(
    transcript_id: int | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Extraction counts grouped by section type."""
    with Database().session() as session:
        q = session.query(
            TranscriptExtractionSchema.section_type, func.count(TranscriptExtractionSchema.id)
        ).group_by(TranscriptExtractionSchema.section_type)

        if transcript_id is not None:
            q = q.filter(TranscriptExtractionSchema.transcript_id == transcript_id)
        elif project_id is not None:
            q = q.filter(
                TranscriptExtractionSchema.transcript_id.in_(
                    _scoped_transcript_ids(session, project_id, worktree_id)
                )
            )

        return [{"type": section_type, "count": count} for section_type, count in q.all()]


# -- Lists --


def get_project_scopes() -> list[dict]:
    """Projects with their worktrees for the unified scope selector."""
    with Database().session() as session:
        projects = session.query(ProjectSchema).order_by(ProjectSchema.name).all()
        return [
            {
                "project_id": p.id,
                "project_name": p.name,
                "worktrees": [{"id": wt.id, "label": wt.label} for wt in sorted(p.worktrees, key=lambda w: w.label)],
            }
            for p in projects
        ]


def _extract_title(session, transcript_id: int) -> str | None:
    """Extract title from the SUMMARY extraction section (first line: '## {title}')."""
    summary = (
        session.query(TranscriptExtractionSchema.text)
        .filter(
            TranscriptExtractionSchema.transcript_id == transcript_id,
            TranscriptExtractionSchema.section_type == SectionType.SUMMARY,
        )
        .first()
    )
    if summary and summary.text and summary.text.startswith("## "):
        return summary.text.split("\n", 1)[0].removeprefix("## ")
    return None


def get_transcripts(
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Transcripts with event and extraction counts.

    worktree_id: None = all, "main" = main repo only, int = specific worktree.
    """
    with Database().session() as session:
        q = session.query(TranscriptSchema)
        if project_id is not None:
            q = q.filter(TranscriptSchema.project_id == project_id)
        if worktree_id == "main":
            q = q.filter(TranscriptSchema.worktree_id.is_(None))
        elif isinstance(worktree_id, int):
            q = q.filter(TranscriptSchema.worktree_id == worktree_id)

        rows = q.order_by(TranscriptSchema.started_at.desc()).all()
        results = []
        for r in rows:
            event_count = (
                session.query(func.count(RawEventSchema.id)).filter(RawEventSchema.transcript_id == r.id).scalar()
            )
            extraction_count = (
                session.query(func.count(TranscriptExtractionSchema.id))
                .filter(TranscriptExtractionSchema.transcript_id == r.id)
                .scalar()
            )
            title = _extract_title(session, r.id)
            results.append(
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "title": title,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "event_count": event_count,
                    "extraction_count": extraction_count,
                }
            )
        return results


def get_extractions(
    transcript_id: int | None = None,
    section_type: str | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Extraction sections with text preview."""
    with Database().session() as session:
        q = session.query(TranscriptExtractionSchema)
        if transcript_id is not None:
            q = q.filter(TranscriptExtractionSchema.transcript_id == transcript_id)
        elif project_id is not None:
            q = q.filter(
                TranscriptExtractionSchema.transcript_id.in_(
                    _scoped_transcript_ids(session, project_id, worktree_id)
                )
            )
        if section_type is not None:
            q = q.filter(TranscriptExtractionSchema.section_type == section_type)

        rows = q.order_by(TranscriptExtractionSchema.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "type": r.section_type,
                "text": r.text,
                "transcript_id": r.transcript_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_extraction_detail(extraction_id: int) -> dict | None:
    """Single extraction section with full text."""
    with Database().session() as session:
        row = session.get(TranscriptExtractionSchema, extraction_id)
        if row is None:
            return None

        return {
            "id": row.id,
            "type": row.section_type,
            "text": row.text,
            "transcript_id": row.transcript_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# -- Timeline --


def get_timeline_events(transcript_id: int) -> list[dict]:
    """Chronological interleaving of raw events and extraction sections for a transcript."""
    with Database().session() as session:
        events = (
            session.query(RawEventSchema)
            .filter(RawEventSchema.transcript_id == transcript_id)
            .order_by(RawEventSchema.timestamp)
            .all()
        )
        extractions = (
            session.query(TranscriptExtractionSchema)
            .filter(TranscriptExtractionSchema.transcript_id == transcript_id)
            .order_by(TranscriptExtractionSchema.created_at)
            .all()
        )

        timeline: list[dict] = []
        status_labels = {s: s.name.lower() for s in RawEventStatus}
        for e in events:
            timeline.append(
                {
                    "kind": "event",
                    "timestamp": e.timestamp.isoformat(),
                    "event_type": e.event_type,
                    "status": status_labels.get(e.processed, str(e.processed)),
                    "id": e.id,
                }
            )
        timeline.extend(
            {
                "kind": "extraction",
                "timestamp": x.created_at.isoformat() if x.created_at else "",
                "section_type": x.section_type,
                "text": x.text,
                "id": x.id,
            }
            for x in extractions
        )

        timeline.sort(key=lambda x: x["timestamp"])
        return timeline
