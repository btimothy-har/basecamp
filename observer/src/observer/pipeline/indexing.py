"""Search index pipeline — syncs the search_index table from extraction sections.

Runs as a batch processor on the daemon's polling cadence. Reads from
transcript extraction sections, encodes with sentence-transformers, and writes
entries to the ``search_index`` table.

SUMMARY sections are indexed as TRANSCRIPT_SUMMARY; all other section types
(KNOWLEDGE, DECISIONS, CONSTRAINTS, ACTIONS) are indexed as TRANSCRIPT_EXTRACTION.
Both use upsert-on-change (mutable text, detected via content hash).
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
from observer.data.enums import SearchSourceType, SectionType
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


def _source_type_for(section_type: str) -> str:
    """Map a SectionType to its SearchSourceType value."""
    if section_type == SectionType.SUMMARY:
        return SearchSourceType.TRANSCRIPT_SUMMARY.value
    return SearchSourceType.TRANSCRIPT_EXTRACTION.value


class SearchIndexer:
    """Syncs the search_index table from transcript extraction sections."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any extraction sections need indexing."""
        with Database().session() as session:
            extractions = (
                session.query(
                    TranscriptExtractionSchema.id,
                    TranscriptExtractionSchema.section_type,
                    TranscriptExtractionSchema.text,
                )
                .all()
            )

            for ext_id, section_type, text in extractions:
                source_type = _source_type_for(section_type)
                existing = (
                    session.query(SearchIndexSchema.content_hash)
                    .filter(
                        SearchIndexSchema.source_type == source_type,
                        SearchIndexSchema.source_id == ext_id,
                    )
                    .first()
                )
                if existing is None:
                    return True
                if existing.content_hash != _content_hash(text):
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
                    TranscriptSchema.project_id,
                    SearchIndexSchema.id.label("index_id"),
                    SearchIndexSchema.content_hash,
                )
                .join(
                    TranscriptSchema,
                    TranscriptExtractionSchema.transcript_id == TranscriptSchema.id,
                )
                .outerjoin(
                    SearchIndexSchema,
                    and_(
                        SearchIndexSchema.source_id == TranscriptExtractionSchema.id,
                        SearchIndexSchema.source_type.in_([
                            SearchSourceType.TRANSCRIPT_SUMMARY.value,
                            SearchSourceType.TRANSCRIPT_EXTRACTION.value,
                        ]),
                    ),
                )
                .all()
            )

        # Filter in Python: new (no index entry) or changed (hash mismatch)
        to_index: list[tuple] = []
        for row in extraction_rows:
            current_hash = _content_hash(row.text)
            if row.index_id is None or row.content_hash != current_hash:
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
                source_type = _source_type_for(row.section_type)

                if row.index_id is None:
                    session.add(
                        SearchIndexSchema(
                            source_type=source_type,
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
