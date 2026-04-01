"""Sentence-transformer embedding model — lazy singleton for observer."""

from __future__ import annotations

from typing import Any

from observer.constants import EMBEDDING_MODEL_NAME, MODEL_CACHE_DIR

_model: Any | None = None


def get_model() -> Any:
    """Return the embedding model, loading it on first call."""
    global _model  # noqa: PLW0603
    if _model is None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR))
    return _model
