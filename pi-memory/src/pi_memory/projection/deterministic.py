"""Deterministic in-memory projection implementations for tests."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pi_memory.db.constants import MEMORY_PROJECTION_COLLECTION_NAME
from pi_memory.projection.contracts import ProjectionDocument, ProjectionHit, ProjectionMetadataValue


class DeterministicEmbeddingProvider:
    """Stable hash-based embedding provider for deterministic tests."""

    def __init__(self, model_name: str = "deterministic-test-model", *, dimension: int = 8) -> None:
        self._model_name = model_name
        self.dimension = dimension

    @property
    def model_name(self) -> str:
        """Return the configured test model name."""
        return self._model_name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Return stable, normalized vectors for the supplied texts."""
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256(f"{self._model_name}\0{text}".encode()).digest()
        values = [((digest[index % len(digest)] / 255.0) * 2.0) - 1.0 for index in range(self.dimension)]
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return [0.0 for _ in values]
        return [value / norm for value in values]


@dataclass(frozen=True)
class _StoredDocument:
    document: ProjectionDocument
    embedding: list[float]


class DeterministicMemoryProjection:
    """In-memory projection with cosine-distance lookup and metadata equality filters."""

    def __init__(
        self,
        collection_name: str = MEMORY_PROJECTION_COLLECTION_NAME,
        embedding_provider: DeterministicEmbeddingProvider | None = None,
    ) -> None:
        self._collection_name = collection_name
        self._embedding_provider = embedding_provider or DeterministicEmbeddingProvider()
        self._documents: dict[str, _StoredDocument] = {}

    @property
    def collection_name(self) -> str:
        """Return the configured collection name."""
        return self._collection_name

    @property
    def embedding_model(self) -> str:
        """Return the embedding model identifier."""
        return self._embedding_provider.model_name

    def upsert(self, documents: Sequence[ProjectionDocument]) -> None:
        """Insert or replace documents in memory."""
        embeddings = self._embedding_provider.embed([document.text for document in documents])
        for document, embedding in zip(documents, embeddings, strict=True):
            self._documents[document.chroma_id] = _StoredDocument(document=document, embedding=embedding)

    def query(
        self,
        text: str,
        *,
        filters: Mapping[str, ProjectionMetadataValue] | None = None,
        limit: int = 10,
    ) -> list[ProjectionHit]:
        """Return nearest documents matching exact metadata filters."""
        query_embedding = self._embedding_provider.embed([text])[0]
        hits = [
            ProjectionHit(
                chroma_id=stored.document.chroma_id,
                text=stored.document.text,
                metadata=dict(stored.document.metadata),
                distance=_cosine_distance(query_embedding, stored.embedding),
            )
            for stored in self._documents.values()
            if _matches_filters(stored.document.metadata, filters)
        ]
        return sorted(hits, key=lambda hit: (hit.distance, hit.chroma_id))[:limit]


def _matches_filters(
    metadata: Mapping[str, ProjectionMetadataValue],
    filters: Mapping[str, ProjectionMetadataValue] | None,
) -> bool:
    if not filters:
        return True
    return all(metadata.get(key) == value for key, value in filters.items())


def _cosine_distance(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 1.0
    similarity = sum(left_value * right_value for left_value, right_value in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    return 1.0 - max(-1.0, min(1.0, similarity))
