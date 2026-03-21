"""Search engine — two retrieval pathways over the search index.

- ``search_artifacts``: KNN over transcript extraction entries → score → dedup.
  Returns specific facts, decisions, actions, and constraints.
- ``search_transcripts``: KNN over transcript summary entries → score → dedup.
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
from observer.data.enums import SearchSourceType, SectionType
from observer.data.schemas import (
    ProjectSchema,
    SearchIndexSchema,
    TranscriptExtractionSchema,
    TranscriptSchema,
    WorktreeSchema,
)
from observer.mcp.scoring import compute_score, deduplicate
from observer.services.db import Database

logger = logging.getLogger(__name__)

# Single-element cache — mutates the list rather than rebinding a name, so no
# `global` statement is needed. Thread safety is not a concern: this module is
# only used by the observer-search MCP server, which is a single-process stdio
# server with no concurrent callers.
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

    The query must already have SearchIndexSchema in the FROM clause.
    TranscriptSchema is joined only when needed (worktree or session exclusion).
    """
    if project_name is not None:
        q = q.join(ProjectSchema, SearchIndexSchema.project_id == ProjectSchema.id).filter(
            ProjectSchema.name == project_name,
        )

    needs_transcript_join = worktree is not None or session_id is not None
    if needs_transcript_join:
        q = q.join(TranscriptSchema, SearchIndexSchema.transcript_id == TranscriptSchema.id)

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
    """Semantic search over transcript extraction index entries.

    Finds specific extracted knowledge, decisions, actions, and constraints
    from past sessions.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        distance_expr = SearchIndexSchema.embedding.cosine_distance(query_vector)
        q = (
            session.query(
                SearchIndexSchema,
                TranscriptExtractionSchema.section_type,
                distance_expr.label("distance"),
            )
            .outerjoin(
                TranscriptExtractionSchema,
                SearchIndexSchema.source_id == TranscriptExtractionSchema.id,
            )
            .filter(
                SearchIndexSchema.embedding.isnot(None),
                SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_EXTRACTION.value,
            )
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree, session_id=session_id)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for index_entry, section_type, distance in rows:
            score = compute_score(distance, index_entry.created_at)
            if score < threshold:
                continue

            result: dict[str, Any] = {
                "source_id": index_entry.source_id,
                "text": index_entry.text,
                "score": round(score, 4),
                "created_at": index_entry.created_at.isoformat() if index_entry.created_at else None,
                "transcript_id": index_entry.transcript_id,
                "_embedding": index_entry.embedding,
            }

            if section_type is not None:
                result["type"] = section_type

            scored.append(result)

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
    """Semantic search over transcript summary index entries.

    Finds sessions whose summaries are semantically relevant to the query.
    Returns session-level matches for orientation — use get_transcript_summary
    to drill down into the full structured summary.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        distance_expr = SearchIndexSchema.embedding.cosine_distance(query_vector)
        q = session.query(
            SearchIndexSchema,
            distance_expr.label("distance"),
        ).filter(
            SearchIndexSchema.embedding.isnot(None),
            SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
        )

        q = _apply_scope_filters(q, project_name=project_name, worktree=worktree, session_id=session_id)
        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for index_entry, distance in rows:
            score = compute_score(distance, index_entry.created_at)
            if score < threshold:
                continue

            # Title is embedded as the first line of the SUMMARY section: "## {title}"
            title = None
            if index_entry.text and index_entry.text.startswith("## "):
                title = index_entry.text.split("\n", 1)[0].removeprefix("## ")

            result: dict[str, Any] = {
                "source_id": index_entry.source_id,
                "text": index_entry.text,
                "score": round(score, 4),
                "created_at": index_entry.created_at.isoformat() if index_entry.created_at else None,
                "transcript_id": index_entry.transcript_id,
                "_embedding": index_entry.embedding,
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


def _extraction_sections_dict(session, transcript_id: int) -> dict[str, str]:
    """Query extraction sections for a transcript, returned as {section_type: text}."""
    rows = (
        session.query(TranscriptExtractionSchema)
        .filter(TranscriptExtractionSchema.transcript_id == transcript_id)
        .all()
    )
    return {row.section_type: row.text for row in rows}


def get_extraction(extraction_id: int) -> dict[str, Any] | None:
    """Retrieve a single transcript extraction section by ID."""
    db = Database()
    with db.session() as session:
        row = session.get(TranscriptExtractionSchema, extraction_id)
        if row is None:
            return None

        return {
            "id": row.id,
            "section_type": row.section_type,
            "text": row.text,
            "transcript_id": row.transcript_id,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def get_transcript_summary(transcript_id: int) -> dict[str, Any] | None:
    """Retrieve a transcript's extraction sections and metadata for drill-down."""
    db = Database()
    with db.session() as session:
        row = session.get(TranscriptSchema, transcript_id)
        if row is None:
            return None

        sections = _extraction_sections_dict(session, transcript_id)

        # Extract title from the SUMMARY section (first line: "## {title}")
        title = None
        summary_text = sections.get(SectionType.SUMMARY)
        if summary_text and summary_text.startswith("## "):
            title = summary_text.split("\n", 1)[0].removeprefix("## ")

        return {
            "id": row.id,
            "title": title,
            "session_id": row.session_id,
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "sections": sections,
        }


def get_session(session_id: str) -> dict[str, Any] | None:
    """Retrieve a session's transcript and extraction sections by Claude session ID.

    Direct lookup — no embeddings or search involved. Used by the main agent
    to check on dispatched worker sessions.
    """
    db = Database()
    with db.session() as session:
        row = session.query(TranscriptSchema).filter(TranscriptSchema.session_id == session_id).first()
        if row is None:
            return None

        sections = _extraction_sections_dict(session, row.id)

        return {
            "session_id": row.session_id,
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "sections": sections,
        }
