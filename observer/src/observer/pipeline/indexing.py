"""Search indexing pipeline — embeds artifact sections.

Reads artifacts that need embedding, encodes with sentence-transformers,
and updates the artifact rows with embedding vectors.
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
from observer.data.artifact import Artifact
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
    """Embeds artifacts for semantic search."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any artifacts need embedding."""
        return Artifact.has_pending_index()

    @staticmethod
    def index_batch(
        db: Database,
        *,
        transcript_id: int | None = None,
        batch_limit: int = EMBEDDING_BATCH_LIMIT,
    ) -> int:
        """Embed a batch of pending artifacts. Returns count of rows updated."""
        to_index = Artifact.get_pending_index(transcript_id=transcript_id)[:batch_limit]

        if not to_index:
            return 0

        texts = [a.text for a in to_index]
        embeddings = _encode(texts)

        now = datetime.now(UTC)
        with db.session() as session:
            for artifact, embedding in zip(to_index, embeddings, strict=True):
                artifact.update_embedding(
                    session,
                    embedding=embedding.tolist(),
                    content_hash=_content_hash(artifact.text),
                    indexed_at=now,
                )

        logger.info("Indexed %d artifacts", len(to_index))
        return len(to_index)


def _encode(texts: list[str]) -> list:
    """Encode texts into embedding vectors. Lazy-loads model."""
    model = _get_model()
    embeddings = model.encode(texts, show_progress_bar=False)

    expected = (len(texts), EMBEDDING_DIMENSIONS)
    if embeddings.shape != expected:
        raise EmbeddingShapeError(expected, embeddings.shape)

    return embeddings
