"""Search indexing pipeline — embeds transcript extraction sections.

Runs as a batch processor on the daemon's polling cadence. Reads extraction
sections that need embedding, encodes with sentence-transformers, and updates
the extraction rows with embedding vectors.
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
from observer.data.transcript_extraction import TranscriptExtraction
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
    """Embeds transcript extraction sections for semantic search."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any extraction sections need embedding."""
        return TranscriptExtraction.has_pending_index()

    @staticmethod
    def index_batch(
        db: Database,
        *,
        batch_limit: int = EMBEDDING_BATCH_LIMIT,
    ) -> int:
        """Embed a batch of pending extraction sections. Returns count of rows updated."""
        to_index = TranscriptExtraction.get_pending_index()[:batch_limit]

        if not to_index:
            return 0

        texts = [e.text for e in to_index]
        embeddings = _encode(texts)

        now = datetime.now(UTC)
        with db.session() as session:
            for extraction, embedding in zip(to_index, embeddings, strict=True):
                extraction.update_embedding(
                    session,
                    embedding=embedding.tolist(),
                    content_hash=_content_hash(extraction.text),
                    indexed_at=now,
                )

        logger.info("Indexed %d extraction sections", len(to_index))
        return len(to_index)


def _encode(texts: list[str]) -> list:
    """Encode texts into embedding vectors. Lazy-loads model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)

    expected = (len(texts), EMBEDDING_DIMENSIONS)
    if embeddings.shape != expected:
        raise EmbeddingShapeError(expected, embeddings.shape)

    return embeddings
