"""Search index pipeline — syncs the search_index table from source tables.

Runs as a batch processor on the daemon's polling cadence. Reads from artifacts
and transcript summaries, encodes with sentence-transformers, and writes entries
to the ``search_index`` table.

Artifacts are insert-once (immutable text). Transcript summaries are
upsert-on-change (mutable text, detected via content hash).
"""

import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import and_

from observer.constants import (
    EMBEDDING_BATCH_LIMIT,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_NAME,
    MODEL_CACHE_DIR,
)
from observer.data.enums import SearchSourceType
from observer.data.schemas import ArtifactSchema, SearchIndexSchema, TranscriptSchema
from observer.exceptions import EmbeddingShapeError
from observer.services.db import Database

logger = logging.getLogger(__name__)

_model_cache: list = []


def _get_model():
    """Return cached embedding model, loading once on first use."""
    if not _model_cache:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model_cache.append(SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR)))
    return _model_cache[0]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class SearchIndexer:
    """Syncs the search_index table from source tables."""

    @staticmethod
    def has_pending(*, skip_artifacts: bool = False) -> bool:
        """Check if any sources need indexing."""
        with Database().session() as session:
            if not skip_artifacts:
                # Check 1: unindexed artifacts
                unindexed_artifact = (
                    session.query(ArtifactSchema.id)
                    .outerjoin(
                        SearchIndexSchema,
                        and_(
                            SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value,
                            SearchIndexSchema.source_id == ArtifactSchema.id,
                        ),
                    )
                    .filter(
                        SearchIndexSchema.id.is_(None),
                        ArtifactSchema.transcript_id.isnot(None),
                    )
                    .limit(1)
                    .first()
                )
                if unindexed_artifact is not None:
                    return True

            # Check 2: transcript summaries needing indexing (new or changed)
            unindexed_summary = (
                session.query(TranscriptSchema.id)
                .outerjoin(
                    SearchIndexSchema,
                    and_(
                        SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                        SearchIndexSchema.source_id == TranscriptSchema.id,
                    ),
                )
                .filter(
                    TranscriptSchema.summary.isnot(None),
                    SearchIndexSchema.id.is_(None),
                )
                .limit(1)
                .first()
            )
            if unindexed_summary is not None:
                return True

            # Check 3: transcript summaries with stale hash — compare in Python
            # Volume is small (one entry per transcript), so fetch all and compare.
            indexed_summaries = (
                session.query(TranscriptSchema.id, TranscriptSchema.summary, SearchIndexSchema.content_hash)
                .join(
                    SearchIndexSchema,
                    and_(
                        SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                        SearchIndexSchema.source_id == TranscriptSchema.id,
                    ),
                )
                .filter(TranscriptSchema.summary.isnot(None))
                .all()
            )
            return any(_content_hash(summary) != stored_hash for _, summary, stored_hash in indexed_summaries)

    @staticmethod
    def index_batch(
        db: Database,
        *,
        batch_limit: int = EMBEDDING_BATCH_LIMIT,
        skip_artifacts: bool = False,
    ) -> int:
        """Index a batch of pending sources. Returns count of entries written."""
        total = 0

        # Phase 1: Index new artifacts (skipped in lite mode)
        if not skip_artifacts:
            with db.session() as session:
                rows = (
                    session.query(
                        ArtifactSchema.id,
                        ArtifactSchema.text,
                        ArtifactSchema.transcript_id,
                        ArtifactSchema.created_at,
                        TranscriptSchema.project_id,
                    )
                    .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
                    .outerjoin(
                        SearchIndexSchema,
                        and_(
                            SearchIndexSchema.source_type == SearchSourceType.ARTIFACT.value,
                            SearchIndexSchema.source_id == ArtifactSchema.id,
                        ),
                    )
                    .filter(
                        SearchIndexSchema.id.is_(None),
                        ArtifactSchema.transcript_id.isnot(None),
                    )
                    .limit(batch_limit)
                    .all()
                )

            if rows:
                texts = [r.text for r in rows]
                embeddings = _encode(texts)

                with db.session() as session:
                    for row, embedding in zip(rows, embeddings, strict=True):
                        session.add(
                            SearchIndexSchema(
                                source_type=SearchSourceType.ARTIFACT.value,
                                source_id=row.id,
                                project_id=row.project_id,
                                transcript_id=row.transcript_id,
                                text=row.text,
                                content_hash=_content_hash(row.text),
                                created_at=row.created_at,
                                embedding=embedding.tolist(),
                            )
                        )

                total += len(rows)
                logger.info("Indexed %d artifacts", len(rows))

        # Phase 2: Index new/changed transcript summaries
        remaining = batch_limit - total
        if remaining <= 0:
            return total

        with db.session() as session:
            # Get all transcripts with summaries + their existing index entries (if any)
            summary_rows = (
                session.query(
                    TranscriptSchema.id,
                    TranscriptSchema.summary,
                    TranscriptSchema.project_id,
                    TranscriptSchema.started_at,
                    SearchIndexSchema.id.label("index_id"),
                    SearchIndexSchema.content_hash,
                )
                .outerjoin(
                    SearchIndexSchema,
                    and_(
                        SearchIndexSchema.source_type == SearchSourceType.TRANSCRIPT_SUMMARY.value,
                        SearchIndexSchema.source_id == TranscriptSchema.id,
                    ),
                )
                .filter(TranscriptSchema.summary.isnot(None))
                .all()
            )

        # Filter in Python: new (no index entry) or changed (hash mismatch)
        to_index: list[tuple] = []
        for row in summary_rows:
            current_hash = _content_hash(row.summary)
            if row.index_id is None or row.content_hash != current_hash:
                to_index.append(row)

        to_index = to_index[:remaining]

        if to_index:
            texts = [r.summary for r in to_index]
            embeddings = _encode(texts)

            with db.session() as session:
                written = 0
                for row, embedding in zip(to_index, embeddings, strict=True):
                    current_hash = _content_hash(row.summary)

                    if row.index_id is None:
                        # New entry
                        session.add(
                            SearchIndexSchema(
                                source_type=SearchSourceType.TRANSCRIPT_SUMMARY.value,
                                source_id=row.id,
                                project_id=row.project_id,
                                transcript_id=row.id,
                                text=row.summary,
                                content_hash=current_hash,
                                created_at=row.started_at,
                                embedding=embedding.tolist(),
                            )
                        )
                        written += 1
                    else:
                        # Update existing entry
                        entry = session.get(SearchIndexSchema, row.index_id)
                        if entry is None:
                            continue
                        entry.text = row.summary
                        entry.content_hash = current_hash
                        entry.embedding = embedding.tolist()
                        entry.indexed_at = datetime.now(UTC)
                        written += 1

            total += written
            logger.info("Indexed %d transcript summaries", written)

        return total


def _encode(texts: list[str]) -> list:
    """Encode texts into embedding vectors. Lazy-loads model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)

    expected = (len(texts), EMBEDDING_DIMENSIONS)
    if embeddings.shape != expected:
        raise EmbeddingShapeError(expected, embeddings.shape)

    return embeddings
