"""Read-only query layer for the visualization dashboard.

Builds on existing domain models (Artifact, RawEvent, Transcript, Project)
and the Database singleton. Never mutates data — safe for concurrent access with
the daemon via WAL mode.
"""

from __future__ import annotations

from sqlalchemy import func

from observer.data.enums import RawEventStatus
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    RawEventSchema,
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
        artifacts_q = session.query(ArtifactSchema)

        if transcript_id is not None:
            events_q = events_q.filter(RawEventSchema.transcript_id == transcript_id)
            artifacts_q = artifacts_q.filter(ArtifactSchema.transcript_id == transcript_id)
        elif project_id is not None:
            tid_sq = _scoped_transcript_ids(session, project_id, worktree_id)
            events_q = events_q.filter(RawEventSchema.transcript_id.in_(tid_sq))
            artifacts_q = artifacts_q.filter(ArtifactSchema.transcript_id.in_(tid_sq))

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
            "total_artifacts": artifacts_q.count(),
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


def get_artifact_type_counts(
    transcript_id: int | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Artifact counts grouped by type."""
    with Database().session() as session:
        q = session.query(ArtifactSchema.artifact_type, func.count(ArtifactSchema.id)).group_by(
            ArtifactSchema.artifact_type
        )

        if transcript_id is not None:
            q = q.filter(ArtifactSchema.transcript_id == transcript_id)
        elif project_id is not None:
            q = q.filter(ArtifactSchema.transcript_id.in_(_scoped_transcript_ids(session, project_id, worktree_id)))

        return [{"type": artifact_type, "count": count} for artifact_type, count in q.all()]


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


def get_transcripts(
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Transcripts with event and artifact counts.

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
            artifact_count = (
                session.query(func.count(ArtifactSchema.id)).filter(ArtifactSchema.transcript_id == r.id).scalar()
            )
            results.append(
                {
                    "id": r.id,
                    "session_id": r.session_id,
                    "title": r.title,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "summary": r.summary,
                    "event_count": event_count,
                    "artifact_count": artifact_count,
                }
            )
        return results


def get_artifacts(
    transcript_id: int | None = None,
    artifact_type: str | None = None,
    project_id: int | None = None,
    worktree_id: int | None | str = None,
) -> list[dict]:
    """Artifacts with text preview."""
    with Database().session() as session:
        q = session.query(ArtifactSchema)
        if transcript_id is not None:
            q = q.filter(ArtifactSchema.transcript_id == transcript_id)
        elif project_id is not None:
            q = q.filter(ArtifactSchema.transcript_id.in_(_scoped_transcript_ids(session, project_id, worktree_id)))
        if artifact_type is not None:
            q = q.filter(ArtifactSchema.artifact_type == artifact_type)

        rows = q.order_by(ArtifactSchema.created_at.desc()).all()
        return [
            {
                "id": r.id,
                "type": r.artifact_type,
                "text": r.text,
                "source_preview": (r.source[:200] + "...") if r.source and len(r.source) > 200 else r.source,
                "source": r.source,
                "origin": r.origin,
                "transcript_id": r.transcript_id,
                "prompt_event_id": r.prompt_event_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def get_artifact_detail(artifact_id: int) -> dict | None:
    """Single artifact with full source."""
    with Database().session() as session:
        row = session.get(ArtifactSchema, artifact_id)
        if row is None:
            return None

        return {
            "id": row.id,
            "type": row.artifact_type,
            "text": row.text,
            "source": row.source,
            "origin": row.origin,
            "transcript_id": row.transcript_id,
            "prompt_event_id": row.prompt_event_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


# -- Timeline --


def get_timeline_events(transcript_id: int) -> list[dict]:
    """Chronological interleaving of raw events and artifacts for a transcript."""
    with Database().session() as session:
        events = (
            session.query(RawEventSchema)
            .filter(RawEventSchema.transcript_id == transcript_id)
            .order_by(RawEventSchema.timestamp)
            .all()
        )
        artifacts = (
            session.query(ArtifactSchema)
            .filter(ArtifactSchema.transcript_id == transcript_id)
            .order_by(ArtifactSchema.created_at)
            .all()
        )

        timeline: list[dict] = []
        for e in events:
            status_labels = {s: s.name.lower() for s in RawEventStatus}
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
                "kind": "artifact",
                "timestamp": a.created_at.isoformat() if a.created_at else "",
                "artifact_type": a.artifact_type,
                "text": a.text,
                "id": a.id,
            }
            for a in artifacts
        )

        timeline.sort(key=lambda x: x["timestamp"])
        return timeline
