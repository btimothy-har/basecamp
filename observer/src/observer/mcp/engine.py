"""Search engine — two retrieval pathways over artifacts.

- ``search_artifacts``: KNN over non-summary artifacts → score → dedup.
  Returns specific facts, decisions, actions, and constraints.
- ``search_transcripts``: KNN over summary artifacts → score → dedup.
  Returns session-level matches for orientation.
"""

from __future__ import annotations

import logging
from typing import Any

from observer.constants import (
    EMBEDDING_MODEL_NAME,
    MODEL_CACHE_DIR,
    SEARCH_DEFAULT_THRESHOLD,
    SEARCH_DEFAULT_TOP_K,
    SEARCH_OVERFETCH_FACTOR,
)
from observer.data.artifact import Artifact
from observer.data.enums import SectionType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    TranscriptSchema,
    WorktreeSchema,
)
from observer.data.transcript import Transcript
from observer.mcp.scoring import compute_score, deduplicate
from observer.services.db import Database

logger = logging.getLogger(__name__)

_model_cache: list[Any] = []


def _get_model() -> Any:
    """Return the embedding model, loading it on first call.

    sentence_transformers is imported lazily so that importing this module does
    not trigger PyTorch initialization — keeping MCP server boot fast.
    """
    if not _model_cache:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model_cache.append(SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR)))
    return _model_cache[0]


def _apply_scope_filters(q, *, project_name, worktree):
    """Apply project and worktree filters to a query.

    The query must already have ArtifactSchema in the FROM clause.
    Joins TranscriptSchema when needed (project or worktree filtering).
    """
    needs_transcript_join = project_name is not None or worktree is not None
    if needs_transcript_join:
        q = q.join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)

    if project_name is not None:
        q = q.join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id).filter(
            ProjectSchema.name == project_name,
        )

    if worktree is not None:
        q = q.join(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id).filter(
            WorktreeSchema.label == worktree
        )

    return q


def search_artifacts(
    query: str,
    project_name: str | None,
    *,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over non-summary extraction sections.

    Finds specific extracted knowledge, decisions, actions, and constraints
    from past sessions.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        distance_expr = ArtifactSchema.embedding.cosine_distance(query_vector)
        q = session.query(
            ArtifactSchema,
            distance_expr.label("distance"),
        ).filter(
            ArtifactSchema.embedding.isnot(None),
            ArtifactSchema.section_type != SectionType.SUMMARY,
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for artifact, distance in rows:
            score = compute_score(distance, artifact.updated_at)
            if score < threshold:
                continue

            scored.append(
                {
                    "artifact_id": artifact.id,
                    "text": artifact.text,
                    "type": artifact.section_type,
                    "score": round(score, 4),
                    "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                    "transcript_id": artifact.transcript_id,
                    "_embedding": artifact.embedding,
                }
            )

        scored.sort(key=lambda r: r["score"], reverse=True)
        results = deduplicate(scored)
        results = results[:top_k]

        for r in results:
            r.pop("_embedding", None)

    return results


def search_transcripts(
    query: str,
    project_name: str | None,
    *,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over summary extraction sections.

    Finds sessions whose summaries are semantically relevant to the query.
    Returns session-level matches for orientation — use get_transcript_detail
    to drill down into the full structured sections.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        distance_expr = ArtifactSchema.embedding.cosine_distance(query_vector)
        q = session.query(
            ArtifactSchema,
            distance_expr.label("distance"),
        ).filter(
            ArtifactSchema.embedding.isnot(None),
            ArtifactSchema.section_type == SectionType.SUMMARY,
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for artifact, distance in rows:
            score = compute_score(distance, artifact.updated_at)
            if score < threshold:
                continue

            title = Artifact.parse_title(artifact.text)

            result: dict[str, Any] = {
                "artifact_id": artifact.id,
                "text": artifact.text,
                "score": round(score, 4),
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                "transcript_id": artifact.transcript_id,
                "_embedding": artifact.embedding,
            }

            if title is not None:
                result["title"] = title

            scored.append(result)

        scored.sort(key=lambda r: r["score"], reverse=True)
        results = deduplicate(scored)
        results = results[:top_k]

        for r in results:
            r.pop("_embedding", None)

    return results


def _sections_dict(transcript_id: int) -> dict[str, str]:
    """Get artifact sections for a transcript as {section_type: text}."""
    artifacts = Artifact.get_for_transcript(transcript_id)
    return {a.section_type: a.text for a in artifacts}


def get_artifact(artifact_id: int) -> dict[str, Any] | None:
    """Retrieve a single artifact by ID."""
    artifact = Artifact.get(artifact_id)
    if artifact is None:
        return None

    return {
        "id": artifact.id,
        "section_type": artifact.section_type,
        "text": artifact.text,
        "transcript_id": artifact.transcript_id,
        "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
    }


def get_transcript_detail(transcript_id: int) -> dict[str, Any] | None:
    """Retrieve a transcript's artifact sections and metadata for drill-down."""
    transcript = Transcript.get(transcript_id)
    if transcript is None:
        return None

    sections = _sections_dict(transcript_id)

    title = Artifact.parse_title(sections.get(SectionType.SUMMARY))

    return {
        "id": transcript.id,
        "title": title,
        "session_id": transcript.session_id,
        "started_at": transcript.started_at.isoformat(),
        "ended_at": transcript.ended_at.isoformat() if transcript.ended_at else None,
        "sections": sections,
    }


def get_session(session_id: str) -> dict[str, Any] | None:
    """Retrieve a session's transcript and extraction sections by Claude session ID.

    Direct lookup — no embeddings or search involved. Used by the main agent
    to check on dispatched worker sessions.
    """
    transcript = Transcript.get_by_session_id(session_id)
    if transcript is None:
        return None

    sections = _sections_dict(transcript.id)

    return {
        "session_id": transcript.session_id,
        "started_at": transcript.started_at.isoformat(),
        "ended_at": transcript.ended_at.isoformat() if transcript.ended_at else None,
        "sections": sections,
    }
