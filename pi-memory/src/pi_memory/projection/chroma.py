"""Chroma-backed memory projection adapters."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pi_memory.constants import MEMORY_CHROMA_DIR, MEMORY_MODEL_CACHE_DIR
from pi_memory.db.constants import MEMORY_PROJECTION_COLLECTION_NAME
from pi_memory.projection.contracts import EmbeddingProvider, ProjectionDocument, ProjectionHit, ProjectionMetadataValue


class SentenceTransformerEmbeddingProvider:
    """SentenceTransformer-backed embedding provider with lazy model loading."""

    def __init__(self, model_name: str, *, cache_dir: Path = MEMORY_MODEL_CACHE_DIR) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any | None = None

    @property
    def model_name(self) -> str:
        """Return the sentence-transformer model name."""
        return self._model_name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts using a lazily constructed SentenceTransformer."""
        model = self._get_model()
        embeddings = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [[float(value) for value in embedding] for embedding in embeddings]

    def _get_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._model = SentenceTransformer(self._model_name, cache_folder=str(self._cache_dir))
        return self._model


class ChromaMemoryProjection:
    """Persistent Chroma projection using explicit pi-memory embeddings."""

    def __init__(
        self,
        *,
        collection_name: str = MEMORY_PROJECTION_COLLECTION_NAME,
        embedding_provider: EmbeddingProvider,
        chroma_dir: Path = MEMORY_CHROMA_DIR,
    ) -> None:
        self._collection_name = collection_name
        self._embedding_provider = embedding_provider
        self._chroma_dir = chroma_dir
        self._client: Any | None = None
        self._collection: Any | None = None

    @property
    def collection_name(self) -> str:
        """Return the Chroma collection name."""
        return self._collection_name

    @property
    def embedding_model(self) -> str:
        """Return the configured embedding model name."""
        return self._embedding_provider.model_name

    @property
    def chroma_dir(self) -> Path:
        """Return the Chroma persistence directory."""
        return self._chroma_dir

    def upsert(self, documents: Sequence[ProjectionDocument]) -> None:
        """Upsert documents into the persistent Chroma collection."""
        if not documents:
            return
        embeddings = self._embedding_provider.embed([document.text for document in documents])
        collection = self._get_collection()
        collection.upsert(
            ids=[document.chroma_id for document in documents],
            documents=[document.text for document in documents],
            metadatas=[dict(document.metadata) for document in documents],
            embeddings=embeddings,
        )

    def query(
        self,
        text: str,
        *,
        filters: Mapping[str, ProjectionMetadataValue] | None = None,
        limit: int = 10,
    ) -> list[ProjectionHit]:
        """Query the persistent Chroma collection with exact metadata filters."""
        embedding = self._embedding_provider.embed([text])[0]
        result = self._get_collection().query(
            query_embeddings=[embedding],
            n_results=limit,
            where=dict(filters) if filters else None,
            include=["documents", "metadatas", "distances"],
        )
        return _hits_from_chroma_result(result)

    def close(self) -> None:
        """Drop cached Chroma handles so tests can reset monkeypatched clients."""
        self._collection = None
        self._client = None

    def _get_collection(self) -> Any:
        if self._collection is None:
            self._collection = self._get_client().get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def _get_client(self) -> Any:
        if self._client is None:
            import chromadb  # noqa: PLC0415

            self._chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self._chroma_dir))
        return self._client


def _hits_from_chroma_result(result: Mapping[str, Any]) -> list[ProjectionHit]:
    ids = result.get("ids") or [[]]
    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]
    return [
        ProjectionHit(
            chroma_id=chroma_id,
            text=document,
            metadata=dict(metadata or {}),
            distance=float(distance),
        )
        for chroma_id, document, metadata, distance in zip(
            ids[0],
            documents[0],
            metadatas[0],
            distances[0],
            strict=True,
        )
    ]
