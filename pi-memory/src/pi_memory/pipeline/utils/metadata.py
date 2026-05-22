"""Model metadata helpers for pipeline result payloads."""

from __future__ import annotations

from typing import Any


def safe_model_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {key: metadata[key] for key in ("provider", "model", "mode") if key in metadata}
