"""Projection seam for rebuildable pi-memory semantic indexes."""

from pi_memory.projection.chroma import ChromaMemoryProjection, SentenceTransformerEmbeddingProvider
from pi_memory.projection.contracts import (
    EmbeddingProvider,
    MemoryProjection,
    ProjectionDocument,
    ProjectionHit,
    ProjectionMetadataValue,
)
from pi_memory.projection.deterministic import DeterministicEmbeddingProvider, DeterministicMemoryProjection
from pi_memory.projection.factory import create_memory_projection
from pi_memory.projection.metadata import projection_metadata_from_record

__all__ = [
    "ChromaMemoryProjection",
    "DeterministicEmbeddingProvider",
    "DeterministicMemoryProjection",
    "EmbeddingProvider",
    "MemoryProjection",
    "ProjectionDocument",
    "ProjectionHit",
    "ProjectionMetadataValue",
    "SentenceTransformerEmbeddingProvider",
    "create_memory_projection",
    "projection_metadata_from_record",
]
