from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pi_memory.db.schema import (
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_INDEXED,
    MemoryProjectionRecord,
)
from pi_memory.projection import (
    ChromaMemoryProjection,
    DeterministicEmbeddingProvider,
    DeterministicMemoryProjection,
    ProjectionDocument,
    ProjectionMetadataValue,
    SentenceTransformerEmbeddingProvider,
    create_memory_projection,
    projection_metadata_from_record,
)
from pi_memory.settings import Settings


class StaticEmbeddingProvider:
    def __init__(self, model_name: str = "static-test-model") -> None:
        self._model_name = model_name
        self.calls: list[list[str]] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        batch = list(texts)
        self.calls.append(batch)
        return [[float(index + 1), 0.0] for index, _text in enumerate(batch)]


def test_sentence_transformer_provider_lazy_loads_model_and_returns_float_vectors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_calls: list[dict[str, Any]] = []
    encode_calls: list[dict[str, Any]] = []

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, *, cache_folder: str) -> None:
            model_calls.append({"model_name": model_name, "cache_folder": cache_folder})

        def encode(
            self,
            texts: list[str],
            *,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> list[list[int]]:
            encode_calls.append(
                {
                    "texts": texts,
                    "normalize_embeddings": normalize_embeddings,
                    "show_progress_bar": show_progress_bar,
                },
            )
            return [[1, 2], [3, 4]][: len(texts)]

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=FakeSentenceTransformer),
    )
    provider = SentenceTransformerEmbeddingProvider("fake-model", cache_dir=tmp_path / "models")

    embeddings = provider.embed(["alpha", "beta"])
    second_embeddings = provider.embed(["alpha"])

    assert embeddings == [[1.0, 2.0], [3.0, 4.0]]
    assert second_embeddings == [[1.0, 2.0]]
    assert model_calls == [{"model_name": "fake-model", "cache_folder": str(tmp_path / "models")}]
    assert encode_calls == [
        {"texts": ["alpha", "beta"], "normalize_embeddings": True, "show_progress_bar": False},
        {"texts": ["alpha"], "normalize_embeddings": True, "show_progress_bar": False},
    ]
    assert (tmp_path / "models").is_dir()


def test_deterministic_embedding_is_stable_and_uses_configured_dimension() -> None:
    provider = DeterministicEmbeddingProvider("stable-model", dimension=12)

    first = provider.embed(["same text"])[0]
    second = provider.embed(["same text"])[0]
    different = provider.embed(["different text"])[0]

    assert first == second
    assert len(first) == 12
    assert different != first


def test_deterministic_projection_upserts_queries_and_filters_metadata() -> None:
    provider = DeterministicEmbeddingProvider("projection-model", dimension=8)
    projection = DeterministicMemoryProjection("test_collection", provider)
    documents = [
        ProjectionDocument("doc-1", "alpha text", {"record_type": "session_claim", "recall_visible": True}),
        ProjectionDocument("doc-2", "beta text", {"record_type": "durable_memory", "recall_visible": True}),
        ProjectionDocument("doc-3", "gamma text", {"record_type": "session_claim", "recall_visible": False}),
    ]

    projection.upsert(documents)
    hits = projection.query("alpha text", filters={"record_type": "session_claim"}, limit=10)
    visible_hits = projection.query("alpha text", filters={"record_type": "session_claim", "recall_visible": True})

    assert projection.collection_name == "test_collection"
    assert projection.embedding_model == "projection-model"
    assert {hit.chroma_id for hit in hits} == {"doc-1", "doc-3"}
    assert [hit.chroma_id for hit in visible_hits] == ["doc-1"]
    assert visible_hits[0].distance <= hits[-1].distance


def test_projection_metadata_from_record_includes_scalars_and_omits_none() -> None:
    record = MemoryProjectionRecord(
        collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
        chroma_id="claim-1",
        record_key="snapshot:7:claim:0",
        record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
        memory_layer=MEMORY_LAYER_SHORT_TERM,
        source_table="session_interpretation_snapshots",
        source_id=7,
        snapshot_id=7,
        quality_report_id=None,
        durable_memory_id=None,
        claim_index=0,
        content_hash="abc123",
        embedding_model="test-embedding",
        embedding_dimension=8,
        status=MEMORY_PROJECTION_STATUS_INDEXED,
        recall_visible=True,
        relation_visible=False,
    )

    metadata = projection_metadata_from_record(record)

    assert metadata == {
        "collection_name": MEMORY_PROJECTION_COLLECTION_NAME,
        "record_type": MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
        "memory_layer": MEMORY_LAYER_SHORT_TERM,
        "source_table": "session_interpretation_snapshots",
        "source_id": 7,
        "snapshot_id": 7,
        "claim_index": 0,
        "content_hash": "abc123",
        "embedding_model": "test-embedding",
        "embedding_dimension": 8,
        "projection_status": MEMORY_PROJECTION_STATUS_INDEXED,
        "recall_visible": True,
        "relation_visible": False,
    }
    assert "quality_report_id" not in metadata
    assert "durable_memory_id" not in metadata
    assert all(isinstance(value, str | int | float | bool) for value in metadata.values())


def test_factory_uses_settings_default_collection_and_configured_embedding_model(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "config.json")
    settings.update(embedding_model="settings-model")

    projection = create_memory_projection(settings, chroma_dir=tmp_path / "chroma")

    assert projection.collection_name == MEMORY_PROJECTION_COLLECTION_NAME
    assert projection.embedding_model == "settings-model"
    assert isinstance(projection, ChromaMemoryProjection)
    assert projection.chroma_dir == tmp_path / "chroma"


def test_factory_accepts_injected_embedding_provider_without_loading_real_model(tmp_path: Path) -> None:
    settings = Settings(tmp_path / "config.json")
    settings.update(embedding_model="settings-model")
    provider = StaticEmbeddingProvider("injected-model")

    projection = create_memory_projection(settings, chroma_dir=tmp_path / "chroma", embedding_provider=provider)

    assert projection.collection_name == MEMORY_PROJECTION_COLLECTION_NAME
    assert projection.embedding_model == "injected-model"
    assert isinstance(projection, ChromaMemoryProjection)
    assert projection.chroma_dir == tmp_path / "chroma"
    assert provider.calls == []


def test_chroma_projection_uses_persistent_path_collection_and_explicit_embeddings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    created_clients: list[FakeChromaClient] = []

    class FakeChromaCollection:
        def __init__(self) -> None:
            self.upserts: list[dict[str, Any]] = []
            self.queries: list[dict[str, Any]] = []

        def upsert(
            self,
            *,
            ids: list[str],
            documents: list[str],
            metadatas: list[dict[str, ProjectionMetadataValue]],
            embeddings: list[list[float]],
        ) -> None:
            self.upserts.append(
                {"ids": ids, "documents": documents, "metadatas": metadatas, "embeddings": embeddings},
            )

        def query(
            self,
            *,
            query_embeddings: list[list[float]],
            n_results: int,
            where: Mapping[str, ProjectionMetadataValue] | None,
            include: list[str],
        ) -> dict[str, list[list[Any]]]:
            self.queries.append(
                {
                    "query_embeddings": query_embeddings,
                    "n_results": n_results,
                    "where": where,
                    "include": include,
                },
            )
            return {
                "ids": [["doc-1"]],
                "documents": [["alpha text"]],
                "metadatas": [[{"record_type": "session_claim"}]],
                "distances": [[0.25]],
            }

    class FakeChromaClient:
        def __init__(self, path: str) -> None:
            self.path = path
            self.collection = FakeChromaCollection()
            self.collection_requests: list[dict[str, Any]] = []
            created_clients.append(self)

        def get_or_create_collection(self, *, name: str, metadata: dict[str, str]) -> FakeChromaCollection:
            self.collection_requests.append({"name": name, "metadata": metadata})
            return self.collection

    monkeypatch.setitem(sys.modules, "chromadb", SimpleNamespace(PersistentClient=FakeChromaClient))
    provider = StaticEmbeddingProvider("static-chroma-model")
    projection = ChromaMemoryProjection(
        collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
        embedding_provider=provider,
        chroma_dir=tmp_path / "chroma",
    )

    projection.upsert([ProjectionDocument("doc-1", "alpha text", {"record_type": "session_claim"})])
    hits = projection.query("alpha", filters={"record_type": "session_claim"}, limit=3)

    client = created_clients[0]
    assert client.path == str(tmp_path / "chroma")
    assert client.collection_requests == [
        {"name": MEMORY_PROJECTION_COLLECTION_NAME, "metadata": {"hnsw:space": "cosine"}},
    ]
    assert client.collection.upserts == [
        {
            "ids": ["doc-1"],
            "documents": ["alpha text"],
            "metadatas": [{"record_type": "session_claim"}],
            "embeddings": [[1.0, 0.0]],
        },
    ]
    assert client.collection.queries == [
        {
            "query_embeddings": [[1.0, 0.0]],
            "n_results": 3,
            "where": {"record_type": "session_claim"},
            "include": ["documents", "metadatas", "distances"],
        },
    ]
    assert provider.calls == [["alpha text"], ["alpha"]]
    assert hits[0].chroma_id == "doc-1"
    assert hits[0].distance == 0.25
