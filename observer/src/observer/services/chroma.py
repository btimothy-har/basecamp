"""ChromaDB persistent client and embedding model for observer vector storage."""

from __future__ import annotations

import logging
import threading
from typing import Any

import chromadb

from observer.constants import CHROMA_DIR, EMBEDDING_MODEL_NAME, MODEL_CACHE_DIR

logger = logging.getLogger(__name__)

COLLECTION_NAME = "artifacts"

_state: dict[str, Any] = {}
_lock = threading.Lock()


def _get_model() -> Any:
    """Return the sentence-transformer model, loading on first call."""
    model = _state.get("model")
    if model is None:
        with _lock:
            model = _state.get("model")
            if model is None:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                model = SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR))
                _state["model"] = model
    return model


def get_client() -> chromadb.ClientAPI:
    """Return the ChromaDB persistent client, creating it on first call."""
    client = _state.get("client")
    if client is None:
        with _lock:
            client = _state.get("client")
            if client is None:
                CHROMA_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
                client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                _state["client"] = client
    return client


def get_collection() -> chromadb.Collection:
    """Return (or create) the artifacts collection with cosine distance."""
    return get_client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def encode(texts: list[str]) -> list[list[float]]:
    """Encode texts into embedding vectors."""
    model = _get_model()
    return model.encode(texts, show_progress_bar=False).tolist()


def close() -> None:
    """Reset client and model singletons."""
    with _lock:
        _state.clear()
