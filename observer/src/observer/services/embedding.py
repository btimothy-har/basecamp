"""Sentence-transformer embedding model — lazy singleton for observer."""

from __future__ import annotations

import threading
from typing import Any

from observer.constants import EMBEDDING_MODEL_NAME, MODEL_CACHE_DIR

_cache: dict[str, Any] = {}
_lock = threading.Lock()


def get_model() -> Any:
    """Return the embedding model, loading it on first call."""
    model = _cache.get("model")
    if model is None:
        with _lock:
            model = _cache.get("model")
            if model is None:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415

                MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                model = SentenceTransformer(EMBEDDING_MODEL_NAME, cache_folder=str(MODEL_CACHE_DIR))
                _cache["model"] = model
    return model
