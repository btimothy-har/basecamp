"""Search engine — hybrid retrieval over artifacts.

Each search pathway runs two retrievers in the same DB session:

- **KNN**: cosine distance over pgvector embeddings (semantic similarity)
- **FTS**: PostgreSQL full-text search with ts_rank (keyword relevance)

Results are merged by artifact ID, scored with a weighted blend of both
signals plus time decay, then truncated to top-k.

- ``search_artifacts``: hybrid search over non-summary artifacts.
- ``search_transcripts``: hybrid search over summary artifacts.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session as SASession

from observer.constants import (
    EMBEDDING_MODEL_NAME,
    MODEL_CACHE_DIR,
    SEARCH_DEFAULT_THRESHOLD,
    SEARCH_DEFAULT_TOP_K,
    SEARCH_FTS_CONFIG,
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
from observer.mcp.scoring import compute_score
from observer.services.db import Database

logger = logging.getLogger(__name__)

_model_cache: list[Any] = []


def _get_model() -> Any:
    """Return the embedding model, loading it on first call.

    sentence_transformers is imported lazily so that importing this module does
    not trigger PyTorch initialization at import time.
    """
    if not _model_cache:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model_cache.append(SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR)))
    return _model_cache[0]


def _apply_scope_filters(
    q,
    *,
    project_name: str | None,
    worktree: str | None,
    session_id: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
):
    """Apply project, worktree, session exclusion, and date range filters.

    TranscriptSchema must already be joined by the caller.
    Joins ProjectSchema/WorktreeSchema as needed.

    Date filters use a half-open interval on TranscriptSchema.started_at:
    ``>= after`` (inclusive) and ``< before`` (exclusive).
    """
    if session_id is not None:
        q = q.filter(TranscriptSchema.session_id != session_id)

    if project_name is not None:
        q = q.join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id).filter(
            ProjectSchema.name == project_name,
        )

    if worktree is not None:
        q = q.join(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id).filter(
            WorktreeSchema.label == worktree,
        )

    if after is not None:
        q = q.filter(TranscriptSchema.started_at >= after)

    if before is not None:
        q = q.filter(TranscriptSchema.started_at < before)

    return q


def _hybrid_retrieve(
    db_session: SASession,
    query: str,
    query_vector: list[float],
    type_filter,
    *,
    project_name: str | None,
    worktree: str | None,
    session_id: str | None,
    overfetch: int,
    threshold: float,
    after: datetime | None = None,
    before: datetime | None = None,
) -> dict[int, dict[str, Any]]:
    """Run KNN and FTS retrieval, merge results by artifact ID.

    Returns a dict keyed by artifact ID containing the artifact, its session
    ID, and both relevance signals (0.0 when a retriever didn't find it).
    FTS ranks are normalized within the batch so the max rank maps to 1.0.

    Each retriever's signal is individually gated by *threshold* before
    entering the merge — weak hits from one retriever cannot piggyback on
    the other signal to inflate the final score.
    """
    scope_kw = {
        "project_name": project_name,
        "worktree": worktree,
        "session_id": session_id,
        "after": after,
        "before": before,
    }
    merged: dict[int, dict[str, Any]] = {}

    # --- KNN retrieval (semantic) ---
    distance_expr = ArtifactSchema.embedding.cosine_distance(query_vector)
    knn_q = (
        db_session.query(
            ArtifactSchema,
            TranscriptSchema.session_id,
            distance_expr.label("distance"),
        )
        .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
        .filter(ArtifactSchema.embedding.isnot(None), type_filter)
    )
    knn_q = _apply_scope_filters(knn_q, **scope_kw)

    for artifact, sess_id, distance in knn_q.order_by(distance_expr).limit(overfetch).all():
        similarity = max(0.0, 1.0 - distance)  # Clamp: cosine distance can exceed 1.0 for anti-correlated vectors
        if similarity < threshold:
            continue
        merged[artifact.id] = {
            "artifact": artifact,
            "session_id": sess_id,
            "semantic": similarity,
            "keyword": 0.0,
        }

    # --- FTS retrieval (keyword) ---
    tsquery = func.plainto_tsquery(SEARCH_FTS_CONFIG, query)
    rank_expr = func.ts_rank(ArtifactSchema.search_vector, tsquery)

    fts_q = (
        db_session.query(
            ArtifactSchema,
            TranscriptSchema.session_id,
            rank_expr.label("rank"),
        )
        .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
        .filter(
            ArtifactSchema.search_vector.isnot(None),
            ArtifactSchema.search_vector.op("@@")(tsquery),
            type_filter,
        )
    )
    fts_q = _apply_scope_filters(fts_q, **scope_kw)
    fts_rows = fts_q.order_by(rank_expr.desc()).limit(overfetch).all()

    if fts_rows:
        max_rank = max(rank for _, _, rank in fts_rows)
        for artifact, sess_id, rank in fts_rows:
            normalized = rank / max_rank if max_rank > 0 else 0.0
            if normalized < threshold:
                continue
            if artifact.id in merged:
                merged[artifact.id]["keyword"] = normalized
            else:
                merged[artifact.id] = {
                    "artifact": artifact,
                    "session_id": sess_id,
                    "semantic": 0.0,
                    "keyword": normalized,
                }

    return merged


def search_artifacts(
    query: str,
    project_name: str | None,
    *,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
    session_id: str | None = None,
    section_types: list[str] | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search over non-summary extraction sections.

    Finds specific extracted knowledge, decisions, actions, and constraints
    from past sessions using both semantic similarity and keyword matching.

    ``section_types`` narrows results to the given type values (e.g.
    ``["knowledge", "decisions"]``). When omitted, all non-summary types are
    searched.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    if section_types is not None:
        type_filter = ArtifactSchema.section_type.in_(section_types)
    else:
        type_filter = ArtifactSchema.section_type != SectionType.SUMMARY

    db = Database()

    with db.session() as session:
        merged = _hybrid_retrieve(
            session,
            query,
            query_vector,
            type_filter,
            project_name=project_name,
            worktree=worktree,
            session_id=session_id,
            overfetch=overfetch,
            threshold=threshold,
            after=after,
            before=before,
        )

        if not merged:
            return []

        scored: list[dict[str, Any]] = []
        for hit in merged.values():
            artifact = hit["artifact"]
            score = compute_score(artifact.updated_at, semantic=hit["semantic"], keyword=hit["keyword"])
            if score < threshold:
                continue

            scored.append(
                {
                    "session_id": hit["session_id"],
                    "text": artifact.text,
                    "type": artifact.section_type,
                    "score": round(score, 4),
                    "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                }
            )

        scored.sort(key=lambda r: r["score"], reverse=True)

    return scored[:top_k]


def search_transcripts(
    query: str,
    project_name: str | None,
    *,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
    session_id: str | None = None,
    after: datetime | None = None,
    before: datetime | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search over summary extraction sections.

    Finds sessions whose summaries are relevant to the query using both
    semantic similarity and keyword matching. Returns session-level matches
    for orientation — use get_session to drill down into full sections.
    """
    model = _get_model()
    query_vector = model.encode([query], show_progress_bar=False)[0].tolist()
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    db = Database()

    with db.session() as session:
        merged = _hybrid_retrieve(
            session,
            query,
            query_vector,
            ArtifactSchema.section_type == SectionType.SUMMARY,
            project_name=project_name,
            worktree=worktree,
            session_id=session_id,
            overfetch=overfetch,
            threshold=threshold,
            after=after,
            before=before,
        )

        if not merged:
            return []

        scored: list[dict[str, Any]] = []
        for hit in merged.values():
            artifact = hit["artifact"]
            score = compute_score(artifact.updated_at, semantic=hit["semantic"], keyword=hit["keyword"])
            if score < threshold:
                continue

            title = Artifact.parse_title(artifact.text)

            result: dict[str, Any] = {
                "session_id": hit["session_id"],
                "text": artifact.text,
                "score": round(score, 4),
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            }

            if title is not None:
                result["title"] = title

            scored.append(result)

        scored.sort(key=lambda r: r["score"], reverse=True)

    return scored[:top_k]


def get_session(session_id: str) -> dict[str, Any] | None:
    """Retrieve a session's transcript and extraction sections by Claude session ID.

    Direct lookup — no embeddings or search involved. Used by the main agent
    to check on dispatched worker sessions.
    """
    transcript = Transcript.get_by_session_id(session_id)
    if transcript is None:
        return None

    artifacts = Artifact.get_for_transcript(transcript.id)
    sections = {a.section_type: a.text for a in artifacts}

    return {
        "session_id": transcript.session_id,
        "started_at": transcript.started_at.isoformat(),
        "ended_at": transcript.ended_at.isoformat() if transcript.ended_at else None,
        "sections": sections,
    }


def list_transcripts(
    project_name: str | None,
    *,
    after: datetime | None = None,
    before: datetime | None = None,
    top_k: int = SEARCH_DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """List sessions by date range — no semantic search involved.

    Returns summaries ordered by session start time (newest first).
    Date filters use a half-open interval on TranscriptSchema.started_at.
    """
    db = Database()

    with db.session() as session:
        q = (
            session.query(
                ArtifactSchema,
                TranscriptSchema.session_id,
                TranscriptSchema.started_at,
                TranscriptSchema.ended_at,
            )
            .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
            .filter(ArtifactSchema.section_type == SectionType.SUMMARY)
        )

        if project_name is not None:
            q = q.join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id).filter(
                ProjectSchema.name == project_name,
            )

        if after is not None:
            q = q.filter(TranscriptSchema.started_at >= after)

        if before is not None:
            q = q.filter(TranscriptSchema.started_at < before)

        rows = q.order_by(TranscriptSchema.started_at.desc()).limit(top_k).all()

        results: list[dict[str, Any]] = []
        for artifact, sess_id, started_at, ended_at in rows:
            title = Artifact.parse_title(artifact.text)
            result: dict[str, Any] = {
                "session_id": sess_id,
                "text": artifact.text,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat() if ended_at else None,
            }
            if title is not None:
                result["title"] = title
            results.append(result)

    return results


def list_artifacts(
    project_name: str | None,
    *,
    after: datetime | None = None,
    before: datetime | None = None,
    session_id: str | None = None,
    section_types: list[str] | None = None,
    top_k: int = SEARCH_DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """List artifacts by date range, session, or type — no semantic search involved.

    Returns artifacts ordered by creation time (newest first).
    Date filters use a half-open interval on ArtifactSchema.created_at.
    When *session_id* is provided, results are scoped to that session (inclusion).
    """
    db = Database()

    with db.session() as session:
        q = session.query(
            ArtifactSchema,
            TranscriptSchema.session_id,
            TranscriptSchema.started_at,
            TranscriptSchema.ended_at,
        ).join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)

        if section_types is not None:
            q = q.filter(ArtifactSchema.section_type.in_(section_types))
        else:
            q = q.filter(ArtifactSchema.section_type != SectionType.SUMMARY)

        if project_name is not None:
            q = q.join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id).filter(
                ProjectSchema.name == project_name,
            )

        if session_id is not None:
            q = q.filter(TranscriptSchema.session_id == session_id)

        if after is not None:
            q = q.filter(ArtifactSchema.created_at >= after)

        if before is not None:
            q = q.filter(ArtifactSchema.created_at < before)

        rows = q.order_by(ArtifactSchema.created_at.desc()).limit(top_k).all()

        results = [
            {
                "session_id": sess_id,
                "text": artifact.text,
                "type": artifact.section_type,
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat() if ended_at else None,
            }
            for artifact, sess_id, started_at, ended_at in rows
        ]

    return results
