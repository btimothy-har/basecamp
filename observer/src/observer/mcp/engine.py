"""Search engine — two retrieval pathways over transcript extractions.

- ``search_artifacts``: KNN over non-summary extraction sections → score → dedup.
  Returns specific facts, decisions, actions, and constraints.
- ``search_transcripts``: KNN over summary extraction sections → score → dedup.
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
from observer.data.enums import SectionType
from observer.data.schemas import (
    ProjectSchema,
    TranscriptExtractionSchema,
    TranscriptSchema,
    WorktreeSchema,
)
from observer.data.transcript import Transcript
from observer.data.transcript_extraction import TranscriptExtraction
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


def _apply_scope_filters(q, *, project_name, worktree, session_id):
    """Apply project, worktree, and session exclusion filters to a query.

    The query must already have TranscriptExtractionSchema in the FROM clause.
    Joins TranscriptSchema when needed (project, worktree, or session exclusion).
    """
    needs_transcript_join = project_name is not None or worktree is not None or session_id is not None
    if needs_transcript_join:
        q = q.join(TranscriptSchema, TranscriptExtractionSchema.transcript_id == TranscriptSchema.id)

    if project_name is not None:
        q = q.join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id).filter(
            ProjectSchema.name == project_name,
        )

    if worktree is not None:
        q = q.join(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id).filter(
            WorktreeSchema.label == worktree
        )

    if session_id is not None:
        q = q.filter(TranscriptSchema.session_id != session_id)

    return q


def search_artifacts(
    query: str,
    project_name: str | None,
    *,
    session_id: str | None = None,
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
        distance_expr = TranscriptExtractionSchema.embedding.cosine_distance(query_vector)
        q = (
            session.query(
                TranscriptExtractionSchema,
                distance_expr.label("distance"),
            )
            .filter(
                TranscriptExtractionSchema.embedding.isnot(None),
                TranscriptExtractionSchema.section_type != SectionType.SUMMARY,
            )
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree, session_id=session_id)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for extraction, distance in rows:
            score = compute_score(distance, extraction.created_at)
            if score < threshold:
                continue

            scored.append({
                "source_id": extraction.id,
                "text": extraction.text,
                "type": extraction.section_type,
                "score": round(score, 4),
                "created_at": extraction.created_at.isoformat() if extraction.created_at else None,
                "transcript_id": extraction.transcript_id,
                "_embedding": extraction.embedding,
            })

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
    session_id: str | None = None,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over summary extraction sections.

    Finds sessions whose summaries are semantically relevant to the query.
    Returns session-level matches for orientation — use get_transcript_summary
    to drill down into the full structured summary.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        distance_expr = TranscriptExtractionSchema.embedding.cosine_distance(query_vector)
        q = session.query(
            TranscriptExtractionSchema,
            distance_expr.label("distance"),
        ).filter(
            TranscriptExtractionSchema.embedding.isnot(None),
            TranscriptExtractionSchema.section_type == SectionType.SUMMARY,
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree, session_id=session_id)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for extraction, distance in rows:
            score = compute_score(distance, extraction.created_at)
            if score < threshold:
                continue

            title = TranscriptExtraction.parse_title(extraction.text)

            result: dict[str, Any] = {
                "source_id": extraction.id,
                "text": extraction.text,
                "score": round(score, 4),
                "created_at": extraction.created_at.isoformat() if extraction.created_at else None,
                "transcript_id": extraction.transcript_id,
                "_embedding": extraction.embedding,
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


def _extraction_sections_dict(transcript_id: int) -> dict[str, str]:
    """Get extraction sections for a transcript as {section_type: text}."""
    extractions = TranscriptExtraction.get_for_transcript(transcript_id)
    return {e.section_type: e.text for e in extractions}


def get_extraction(extraction_id: int) -> dict[str, Any] | None:
    """Retrieve a single transcript extraction section by ID."""
    extraction = TranscriptExtraction.get(extraction_id)
    if extraction is None:
        return None

    return {
        "id": extraction.id,
        "section_type": extraction.section_type,
        "text": extraction.text,
        "transcript_id": extraction.transcript_id,
        "created_at": extraction.created_at.isoformat() if extraction.created_at else None,
    }


def get_transcript_summary(transcript_id: int) -> dict[str, Any] | None:
    """Retrieve a transcript's extraction sections and metadata for drill-down."""
    transcript = Transcript.get(transcript_id)
    if transcript is None:
        return None

    sections = _extraction_sections_dict(transcript_id)

    title = TranscriptExtraction.parse_title(sections.get(SectionType.SUMMARY))

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

    sections = _extraction_sections_dict(transcript.id)

    return {
        "session_id": transcript.session_id,
        "started_at": transcript.started_at.isoformat(),
        "ended_at": transcript.ended_at.isoformat() if transcript.ended_at else None,
        "sections": sections,
    }
