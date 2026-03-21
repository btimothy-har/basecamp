"""Search index pipeline — syncs the search_index table from extraction sections.

Runs as a batch processor on the daemon's polling cadence. Reads from
transcript extraction sections, encodes with sentence-transformers, and writes
entries to the ``search_index`` table.

Change detection uses two signals: ``updated_at > indexed_at`` as a fast path,
and ``content_hash`` mismatch as a safety net.
"""

import hashlib
import logging
from datetime import UTC, datetime

from observer.constants import (
    EMBEDDING_BATCH_LIMIT,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_NAME,
    MODEL_CACHE_DIR,
)
from observer.data.schemas import SearchIndexSchema, TranscriptExtractionSchema, TranscriptSchema
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
    """Syncs the search_index table from transcript extraction sections."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any extraction sections need indexing.

        Fast path: new extractions (no index entry) or updated_at > indexed_at.
        Safety net: content_hash mismatch catches any missed updates.
        """
        with Database().session() as session:
            rows = (
                session.query(
                    TranscriptExtractionSchema.id,
                    TranscriptExtractionSchema.text,
                    TranscriptExtractionSchema.updated_at,
                    SearchIndexSchema.indexed_at,
                    SearchIndexSchema.content_hash,
                )
                .outerjoin(
                    SearchIndexSchema,
                    SearchIndexSchema.source_id == TranscriptExtractionSchema.id,
                )
                .all()
            )

            for _, text, updated_at, indexed_at, existing_hash in rows:
                if indexed_at is None:
                    return True
                if updated_at > indexed_at:
                    return True
                if existing_hash != _content_hash(text):
                    return True

            return False

    @staticmethod
    def index_batch(
        db: Database,
        *,
        batch_limit: int = EMBEDDING_BATCH_LIMIT,
    ) -> int:
        """Index a batch of pending extraction sections. Returns count of entries written."""
        with db.session() as session:
            extraction_rows = (
                session.query(
                    TranscriptExtractionSchema.id,
                    TranscriptExtractionSchema.transcript_id,
                    TranscriptExtractionSchema.section_type,
                    TranscriptExtractionSchema.text,
                    TranscriptExtractionSchema.created_at,
                    TranscriptExtractionSchema.updated_at,
                    TranscriptSchema.project_id,
                    SearchIndexSchema.id.label("index_id"),
                    SearchIndexSchema.indexed_at,
                    SearchIndexSchema.content_hash,
                )
                .join(
                    TranscriptSchema,
                    TranscriptExtractionSchema.transcript_id == TranscriptSchema.id,
                )
                .outerjoin(
                    SearchIndexSchema,
                    SearchIndexSchema.source_id == TranscriptExtractionSchema.id,
                )
                .all()
            )

        # Filter: new (no index entry), timestamp stale, or hash mismatch
        to_index: list[tuple] = []
        for row in extraction_rows:
            if row.index_id is None:
                to_index.append(row)
            elif row.updated_at > row.indexed_at:
                to_index.append(row)
            elif row.content_hash != _content_hash(row.text):
                to_index.append(row)

        to_index = to_index[:batch_limit]

        if not to_index:
            return 0

        texts = [r.text for r in to_index]
        embeddings = _encode(texts)

        with db.session() as session:
            written = 0
            for row, embedding in zip(to_index, embeddings, strict=True):
                current_hash = _content_hash(row.text)

                if row.index_id is None:
                    session.add(
                        SearchIndexSchema(
                            section_type=row.section_type,
                            source_id=row.id,
                            project_id=row.project_id,
                            transcript_id=row.transcript_id,
                            text=row.text,
                            content_hash=current_hash,
                            created_at=row.created_at,
                            embedding=embedding.tolist(),
                        )
                    )
                    written += 1
                else:
                    entry = session.get(SearchIndexSchema, row.index_id)
                    if entry is None:
                        continue
                    entry.text = row.text
                    entry.content_hash = current_hash
                    entry.embedding = embedding.tolist()
                    entry.indexed_at = datetime.now(UTC)
                    written += 1

        logger.info("Indexed %d extraction sections", written)
        return written


def _encode(texts: list[str]) -> list:
    """Encode texts into embedding vectors. Lazy-loads model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)

    expected = (len(texts), EMBEDDING_DIMENSIONS)
    if embeddings.shape != expected:
        raise EmbeddingShapeError(expected, embeddings.shape)

    return embeddings
