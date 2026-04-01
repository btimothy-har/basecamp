"""ChromaDB persistent client for observer vector storage."""

from __future__ import annotations

import logging
import threading

import chromadb

from observer.constants import CHROMA_DIR

logger = logging.getLogger(__name__)

COLLECTION_NAME = "artifacts"

_state: dict[str, chromadb.ClientAPI] = {}
_lock = threading.Lock()


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


def close() -> None:
    """Reset the client singleton."""
    with _lock:
        _state.pop("client", None)
