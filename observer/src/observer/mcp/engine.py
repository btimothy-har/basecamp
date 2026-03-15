"""Search engine — two retrieval pathways over the search index.

- ``search_artifacts``: KNN over artifact entries → score → dedup → session
  context expansion. Returns specific facts, decisions, actions, and constraints.
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
    SEARCH_SIBLING_THRESHOLD,
)
from observer.data.enums import SearchSourceType
from observer.data.schemas import (
    ArtifactSchema,
    ProjectSchema,
    SearchIndexSchema,
    TranscriptEventSchema,
    TranscriptSchema,
    WorktreeSchema,
)
from observer.mcp.scoring import compute_score, deduplicate, embedding_similarity
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


def search_artifacts(
    query: str,
    project_name: str,
    *,
    session_id: str | None = None,
    top_k: int = SEARCH_DEFAULT_TOP_K,
    threshold: float = SEARCH_DEFAULT_THRESHOLD,
    worktree: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over artifact index entries with session context expansion.

    Finds specific extracted facts, decisions, actions, and constraints.
    Each result includes sibling artifacts from the same transcript for
    additional context.
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
                ArtifactSchema.artifact_type,
                distance_expr.label("distance"),
            )
            .outerjoin(ArtifactSchema, SearchIndexSchema.source_id == ArtifactSchema.id)
            .join(ProjectSchema, SearchIndexSchema.project_id == ProjectSchema.id)
            .filter(
                SearchIndexSchema.embedding.isnot(None),
                SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value,
                ProjectSchema.name == project_name,
            )
        )

        if worktree is not None:
            q = (
                q.join(TranscriptSchema, SearchIndexSchema.transcript_id == TranscriptSchema.id)
                .join(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id)
                .filter(WorktreeSchema.label == worktree)
            )

        if session_id:
            if worktree is not None:
                q = q.filter(TranscriptSchema.session_id != session_id)
            else:
                q = q.join(TranscriptSchema, SearchIndexSchema.transcript_id == TranscriptSchema.id).filter(
                    TranscriptSchema.session_id != session_id
                )

        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for index_entry, artifact_type, distance in rows:
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

            if artifact_type is not None:
                result["type"] = artifact_type

            scored.append(result)

        scored.sort(key=lambda r: r["score"], reverse=True)
        results = deduplicate(scored)
        results = results[:top_k]

        # Session context expansion — fetch sibling artifact entries from the
        # same transcripts and rank by similarity to the result's embedding.
        result_ids = {r["source_id"] for r in results}
        transcript_ids = {r["transcript_id"] for r in results if r["transcript_id"] is not None}

        siblings_by_transcript: dict[int, list[tuple[int, str, list[float], str | None]]] = {}
        if transcript_ids:
            sibling_rows = (
                session.query(
                    SearchIndexSchema.source_id,
                    SearchIndexSchema.transcript_id,
                    SearchIndexSchema.embedding,
                    ArtifactSchema.artifact_type,
                )
                .join(ArtifactSchema, SearchIndexSchema.source_id == ArtifactSchema.id)
                .filter(
                    SearchIndexSchema.transcript_id.in_(transcript_ids),
                    SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value,
                    SearchIndexSchema.embedding.isnot(None),
                )
                .all()
            )
            for source_id, transcript_id, emb, artifact_type in sibling_rows:
                if source_id not in result_ids:
                    siblings_by_transcript.setdefault(transcript_id, []).append(
                        (source_id, transcript_id, emb, artifact_type)
                    )

        for r in results:
            result_embedding = r.get("_embedding")
            transcript_siblings = siblings_by_transcript.get(r["transcript_id"], [])

            if result_embedding is not None and transcript_siblings:
                scored_siblings = [(s, embedding_similarity(result_embedding, s[2])) for s in transcript_siblings]
                r["session_context"] = [
                    {"id": s[0], "type": s[3]}
                    for s, sim in sorted(scored_siblings, key=lambda x: x[1], reverse=True)
                    if sim >= SEARCH_SIBLING_THRESHOLD
                ]
            else:
                r["session_context"] = []

            r.pop("_embedding", None)

    return results


def search_transcripts(
    query: str,
    project_name: str,
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
        q = (
            session.query(
                SearchIndexSchema,
                TranscriptSchema.title,
                distance_expr.label("distance"),
            )
            .outerjoin(TranscriptSchema, SearchIndexSchema.source_id == TranscriptSchema.id)
            .join(ProjectSchema, SearchIndexSchema.project_id == ProjectSchema.id)
            .filter(
                SearchIndexSchema.embedding.isnot(None),
                SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                ProjectSchema.name == project_name,
            )
        )

        if worktree is not None:
            q = q.join(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id).filter(
                WorktreeSchema.label == worktree
            )

        if session_id:
            q = q.filter(TranscriptSchema.session_id != session_id)

        rows = q.order_by(distance_expr).limit(overfetch).all()

        if not rows:
            return []

        scored: list[dict[str, Any]] = []
        for index_entry, title, distance in rows:
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

            if title is not None:
                result["title"] = title

            scored.append(result)

        scored.sort(key=lambda r: r["score"], reverse=True)
        results = deduplicate(scored)
        results = results[:top_k]

        for r in results:
            r.pop("_embedding", None)

    return results


def get_artifact(artifact_id: int) -> dict[str, Any] | None:
    """Retrieve a single artifact by ID with full details."""
    db = Database()
    with db.session() as session:
        row = session.get(ArtifactSchema, artifact_id)
        if row is None:
            return None

        prompted_by = None
        if row.prompt_event_id is not None:
            prompt_event = session.get(TranscriptEventSchema, row.prompt_event_id)
            if prompt_event is not None:
                prompted_by = prompt_event.text

        return {
            "id": row.id,
            "type": row.artifact_type,
            "text": row.text,
            "origin": row.origin,
            "source": row.source,
            "transcript_id": row.transcript_id,
            "prompted_by": prompted_by,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }


def get_transcript_summary(transcript_id: int) -> dict[str, Any] | None:
    """Retrieve a transcript's summary and metadata for drill-down."""
    db = Database()
    with db.session() as session:
        row = session.get(TranscriptSchema, transcript_id)
        if row is None:
            return None

        return {
            "id": row.id,
            "title": row.title,
            "summary": row.summary,
            "session_id": row.session_id,
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        }


def get_session(session_id: str) -> dict[str, Any] | None:
    """Retrieve a session's transcript and recent artifacts by Claude session ID.

    Direct lookup — no embeddings or search involved. Used by the main agent
    to check on dispatched worker sessions.
    """
    db = Database()
    with db.session() as session:
        row = session.query(TranscriptSchema).filter(TranscriptSchema.session_id == session_id).first()
        if row is None:
            return None

        recent_artifacts = (
            session.query(ArtifactSchema)
            .filter(ArtifactSchema.transcript_id == row.id)
            .order_by(ArtifactSchema.created_at.desc())
            .limit(5)
            .all()
        )

        return {
            "session_id": row.session_id,
            "title": row.title,
            "summary": row.summary,
            "started_at": row.started_at.isoformat(),
            "ended_at": row.ended_at.isoformat() if row.ended_at else None,
            "recent_artifacts": [
                {
                    "id": a.id,
                    "type": a.artifact_type,
                    "text": a.text,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in recent_artifacts
            ],
        }
