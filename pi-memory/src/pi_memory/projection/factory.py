"""Factory for pi-memory-owned Chroma projections."""

from __future__ import annotations

from pathlib import Path

from pi_memory.constants import MEMORY_CHROMA_DIR, MEMORY_PROJECTION_COLLECTION_NAME
from pi_memory.projection.chroma import ChromaMemoryProjection, SentenceTransformerEmbeddingProvider
from pi_memory.projection.contracts import EmbeddingProvider, MemoryProjection
from pi_memory.settings import Settings, settings


def create_memory_projection(
    memory_settings: Settings | None = None,
    *,
    chroma_dir: Path | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> MemoryProjection:
    """Create the default Chroma projection seam for pi-memory.

    Args:
        memory_settings: Optional settings source. Defaults to the process-wide settings.
        chroma_dir: Optional Chroma persistence directory override for tests.
        embedding_provider: Optional embedding provider override for deterministic tests.

    Returns:
        A Chroma-backed projection configured for the pi_memory_records collection.
    """
    effective_settings = memory_settings or settings
    provider = embedding_provider or SentenceTransformerEmbeddingProvider(effective_settings.embedding_model)
    return ChromaMemoryProjection(
        collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
        embedding_provider=provider,
        chroma_dir=chroma_dir or MEMORY_CHROMA_DIR,
    )
