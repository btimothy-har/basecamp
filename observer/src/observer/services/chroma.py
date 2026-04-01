"""ChromaDB persistent client for observer vector storage."""

from __future__ import annotations

import logging

import chromadb

from observer.constants import BASECAMP_DIR, CHROMA_DIR

logger = logging.getLogger(__name__)

COLLECTION_NAME = "artifacts"

_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    """Return the ChromaDB persistent client, creating it on first call."""
    global _client  # noqa: PLW0603
    if _client is None:
        BASECAMP_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return _client


def get_collection() -> chromadb.Collection:
    """Return (or create) the artifacts collection with cosine distance."""
    client = get_client()
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def close() -> None:
    """Reset the client singleton."""
    global _client  # noqa: PLW0603
    _client = None
