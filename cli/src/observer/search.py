"""Search engine — hybrid retrieval over artifacts.

Each search pathway runs two retrievers:

- **KNN**: cosine distance over ChromaDB embeddings (semantic similarity)
- **FTS**: SQLite FTS5 full-text search with BM25 ranking (keyword relevance)

Results are merged by artifact ID, scored with a weighted blend of both
signals plus time decay, then truncated to top-k.

- ``search_artifacts``: hybrid search over non-summary artifacts.
- ``search_transcripts``: hybrid search over summary artifacts.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session as SASession

from observer.constants import (
    SEARCH_DEFAULT_THRESHOLD,
    SEARCH_DEFAULT_TOP_K,
    SEARCH_KEYWORD_WEIGHT,
    SEARCH_OVERFETCH_FACTOR,
    SEARCH_SEMANTIC_WEIGHT,
    SEARCH_TIME_DECAY_POWER,
    SEARCH_TIME_DECAY_SCALE_DAYS,
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
from observer.services import chroma
from observer.services.db import Database

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def time_decay(
    timestamp: datetime,
    scale_days: float = SEARCH_TIME_DECAY_SCALE_DAYS,
    power: float = SEARCH_TIME_DECAY_POWER,
) -> float:
    """Power-law time decay returning a value in (0, 1].

    Returns 0.5 at exactly scale_days. Decays slowly toward 0 but never
    reaches it, so entries of any age remain differentiable by recency.
    """
    now = datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    age_days = max(0.0, (now - timestamp).total_seconds() / 86400)
    return 1.0 / (1.0 + (age_days / scale_days) ** power)


def compute_score(
    timestamp: datetime,
    *,
    semantic: float = 0.0,
    keyword: float = 0.0,
) -> float:
    """Hybrid relevance score blending semantic similarity, keyword match, and recency.

    Relevance is a weighted average of the two retrieval signals. A recency
    bonus (up to 20% of the final score) breaks ties in favour of recent
    entries without burying older ones.
    """
    relevance = semantic * SEARCH_SEMANTIC_WEIGHT + keyword * SEARCH_KEYWORD_WEIGHT
    recency_bonus = time_decay(timestamp) * 0.2
    return min(1.0, relevance * 0.8 + recency_bonus)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


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


def _build_chroma_where(
    *,
    project_name: str | None,
    worktree: str | None,
    session_id: str | None,
    after: datetime | None,
    before: datetime | None,
    section_types: list[str] | None = None,
    section_type_eq: str | None = None,
    section_type_ne: str | None = None,
) -> dict | None:
    """Build a ChromaDB metadata where filter from scope parameters."""
    conditions: list[dict] = []

    if project_name is not None:
        conditions.append({"project_name": {"$eq": project_name}})

    if worktree is not None:
        conditions.append({"worktree_label": {"$eq": worktree}})

    if session_id is not None:
        conditions.append({"session_id": {"$ne": session_id}})

    if after is not None:
        conditions.append({"started_at": {"$gte": after.timestamp()}})

    if before is not None:
        conditions.append({"started_at": {"$lt": before.timestamp()}})

    if section_types is not None:
        conditions.append({"section_type": {"$in": section_types}})
    elif section_type_eq is not None:
        conditions.append({"section_type": {"$eq": section_type_eq}})
    elif section_type_ne is not None:
        conditions.append({"section_type": {"$ne": section_type_ne}})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _knn_retrieve(
    query_vector: list[float],
    *,
    overfetch: int,
    threshold: float,
    project_name: str | None,
    worktree: str | None,
    session_id: str | None,
    after: datetime | None,
    before: datetime | None,
    section_types: list[str] | None = None,
    section_type_eq: str | None = None,
    section_type_ne: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Run KNN retrieval via ChromaDB, return results keyed by artifact ID."""
    collection = chroma.get_collection()

    where = _build_chroma_where(
        project_name=project_name,
        worktree=worktree,
        session_id=session_id,
        after=after,
        before=before,
        section_types=section_types,
        section_type_eq=section_type_eq,
        section_type_ne=section_type_ne,
    )

    query_kwargs: dict[str, Any] = {
        "query_embeddings": [query_vector],
        "n_results": overfetch,
    }
    if where is not None:
        query_kwargs["where"] = where

    try:
        results = collection.query(**query_kwargs)
    except Exception:
        logger.exception("ChromaDB query failed")
        return {}

    if not results or not results["ids"] or not results["ids"][0]:
        return {}

    merged: dict[int, dict[str, Any]] = {}
    ids = results["ids"][0]
    distances = results["distances"][0] if results["distances"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []

    for i, doc_id in enumerate(ids):
        artifact_id = int(doc_id)
        distance = distances[i] if i < len(distances) else 1.0
        similarity = max(0.0, 1.0 - distance)
        if similarity < threshold:
            continue

        meta = metadatas[i] if i < len(metadatas) else {}
        merged[artifact_id] = {
            "artifact_id": artifact_id,
            "session_id": meta.get("session_id", ""),
            "semantic": similarity,
            "keyword": 0.0,
        }

    return merged


def _sanitize_fts5_query(query: str) -> str:
    """Escape user input for safe use in FTS5 MATCH expressions.

    Wraps each whitespace-delimited token in double quotes so FTS5
    treats them as literal strings, not operators. This mirrors
    PostgreSQL's plainto_tsquery behavior.
    """
    tokens = query.split()
    if not tokens:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


def _fts_retrieve(
    db_session: SASession,
    query: str,
    type_filter,
    *,
    overfetch: int,
    threshold: float,
    project_name: str | None,
    worktree: str | None,
    session_id: str | None,
    after: datetime | None,
    before: datetime | None,
) -> dict[int, dict[str, Any]]:
    """Run FTS5 retrieval via SQLite, return results keyed by artifact ID.

    Uses a two-step approach: raw SQL for FTS5 MATCH + bm25() scoring,
    then ORM query for full artifact data with scope filters.
    """
    # Step 1: Get matching rowids and bm25 scores from FTS5
    safe_query = _sanitize_fts5_query(query)
    fts_sql = text(
        "SELECT rowid, bm25(artifacts_fts) AS rank FROM artifacts_fts WHERE artifacts_fts MATCH :query LIMIT :limit"
    ).bindparams(query=safe_query, limit=overfetch * 2)

    try:
        fts_matches = db_session.execute(fts_sql).fetchall()
    except Exception:
        logger.warning("FTS5 query failed for %r, falling back to KNN only", query)
        return {}

    if not fts_matches:
        return {}

    match_ids = [row[0] for row in fts_matches]
    rank_by_id = {row[0]: row[1] for row in fts_matches}

    # Step 2: Load artifacts with scope filters
    art_q = (
        db_session.query(ArtifactSchema, TranscriptSchema.session_id)
        .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
        .filter(ArtifactSchema.id.in_(match_ids), type_filter)
    )
    art_q = _apply_scope_filters(
        art_q,
        project_name=project_name,
        worktree=worktree,
        session_id=session_id,
        after=after,
        before=before,
    )
    art_rows = art_q.limit(overfetch).all()

    if not art_rows:
        return {}

    # BM25 returns negative scores (lower = better match), so negate for ranking
    ranks = [-rank_by_id[artifact.id] for artifact, _ in art_rows]
    max_rank = max(ranks) if ranks else 0.0

    merged: dict[int, dict[str, Any]] = {}
    for (artifact, sess_id), neg_rank in zip(art_rows, ranks):
        normalized = neg_rank / max_rank if max_rank > 0 else 0.0
        if normalized < threshold:
            continue
        merged[artifact.id] = {
            "artifact_id": artifact.id,
            "session_id": sess_id,
            "semantic": 0.0,
            "keyword": normalized,
        }

    return merged


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
    section_types: list[str] | None = None,
    section_type_eq: str | None = None,
    section_type_ne: str | None = None,
) -> dict[int, dict[str, Any]]:
    """Run KNN and FTS retrieval, merge results by artifact ID."""
    scope_kw = {
        "project_name": project_name,
        "worktree": worktree,
        "session_id": session_id,
        "after": after,
        "before": before,
    }

    # KNN retrieval via ChromaDB
    merged = _knn_retrieve(
        query_vector,
        overfetch=overfetch,
        threshold=threshold,
        section_types=section_types,
        section_type_eq=section_type_eq,
        section_type_ne=section_type_ne,
        **scope_kw,
    )

    # FTS retrieval via SQLite FTS5
    fts_results = _fts_retrieve(
        db_session,
        query,
        type_filter,
        overfetch=overfetch,
        threshold=threshold,
        **scope_kw,
    )

    # Merge FTS results into KNN results
    for artifact_id, fts_hit in fts_results.items():
        if artifact_id in merged:
            merged[artifact_id]["keyword"] = fts_hit["keyword"]
        else:
            merged[artifact_id] = fts_hit

    return merged


def _load_artifacts(db_session: SASession, artifact_ids: set[int]) -> dict[int, Any]:
    """Load ArtifactSchema rows by ID for scoring."""
    if not artifact_ids:
        return {}
    rows = db_session.query(ArtifactSchema).filter(ArtifactSchema.id.in_(artifact_ids)).all()
    return {row.id: row for row in rows}


def _score_and_rank(
    merged: dict[int, dict[str, Any]],
    session: SASession,
    *,
    threshold: float,
    top_k: int,
) -> list[tuple[ArtifactSchema, str, float]]:
    """Load, score, filter, and rank merged retrieval results.

    Returns (artifact, session_id, score) tuples sorted by score descending,
    truncated to top_k.
    """
    artifacts_by_id = _load_artifacts(session, set(merged.keys()))

    scored: list[tuple[ArtifactSchema, str, float]] = []
    for hit in merged.values():
        artifact = artifacts_by_id.get(hit["artifact_id"])
        if artifact is None:
            continue
        score = compute_score(artifact.updated_at, semantic=hit["semantic"], keyword=hit["keyword"])
        if score < threshold:
            continue
        scored.append((artifact, hit["session_id"], score))

    scored.sort(key=lambda t: t[2], reverse=True)
    return scored[:top_k]


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
    """Hybrid search over non-summary extraction sections."""
    query_vector = chroma.encode([query])[0]
    overfetch = max(top_k * SEARCH_OVERFETCH_FACTOR, 50)

    if section_types is not None:
        type_filter = ArtifactSchema.section_type.in_(section_types)
        chroma_section_types = section_types
        chroma_section_type_eq = None
        chroma_section_type_ne = None
    else:
        type_filter = ArtifactSchema.section_type != SectionType.SUMMARY
        chroma_section_types = None
        chroma_section_type_eq = None
        chroma_section_type_ne = str(SectionType.SUMMARY)

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
            section_types=chroma_section_types,
            section_type_eq=chroma_section_type_eq,
            section_type_ne=chroma_section_type_ne,
        )

        if not merged:
            return []

        return [
            {
                "session_id": sess_id,
                "text": artifact.text,
                "type": artifact.section_type,
                "score": round(score, 4),
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            }
            for artifact, sess_id, score in _score_and_rank(merged, session, threshold=threshold, top_k=top_k)
        ]


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
    """Hybrid search over summary extraction sections."""
    query_vector = chroma.encode([query])[0]
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
            section_type_eq=str(SectionType.SUMMARY),
        )

        if not merged:
            return []

        results: list[dict[str, Any]] = []
        for artifact, sess_id, score in _score_and_rank(merged, session, threshold=threshold, top_k=top_k):
            title = Artifact.parse_title(artifact.text)
            result: dict[str, Any] = {
                "session_id": sess_id,
                "text": artifact.text,
                "score": round(score, 4),
                "created_at": artifact.created_at.isoformat() if artifact.created_at else None,
            }
            if title is not None:
                result["title"] = title
            results.append(result)

        return results


def get_session(session_id: str) -> dict[str, Any] | None:
    """Retrieve a session's transcript and extraction sections by Claude session ID."""
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
    """List sessions by date range — no semantic search involved."""
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
    """List artifacts by date range, session, or type — no semantic search involved."""
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
