"""Typed contracts for rebuildable memory projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

type ProjectionMetadataValue = str | int | float | bool


@dataclass(frozen=True)
class ProjectionDocument:
    """A document ready to project into Chroma."""

    chroma_id: str
    text: str
    metadata: Mapping[str, ProjectionMetadataValue]


@dataclass(frozen=True)
class ProjectionHit:
    """A projection query result."""

    chroma_id: str
    text: str
    metadata: Mapping[str, ProjectionMetadataValue]
    distance: float


class EmbeddingProvider(Protocol):
    """Embeds text for memory projection storage and lookup."""

    @property
    def model_name(self) -> str:
        """Return the embedding model identifier."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts into vectors."""


class MemoryProjection(Protocol):
    """Rebuildable semantic projection over canonical SQLite memory records."""

    @property
    def collection_name(self) -> str:
        """Return the Chroma collection name."""

    @property
    def embedding_model(self) -> str:
        """Return the embedding model identifier used by this projection."""

    def upsert(self, documents: Sequence[ProjectionDocument]) -> None:
        """Insert or replace projection documents."""

    def query(
        self,
        text: str,
        *,
        filters: Mapping[str, ProjectionMetadataValue] | None = None,
        limit: int = 10,
    ) -> list[ProjectionHit]:
        """Return nearest projection hits for text."""
