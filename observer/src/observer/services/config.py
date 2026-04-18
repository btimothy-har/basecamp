"""Persistent configuration for observer.

Stores user-configured settings in a JSON file at
~/.basecamp/observer/config.json so they are available across all invocation
paths — CLI commands, hooks — without relying on shell environment variables.

Model identifiers use pydantic-ai's ``provider:model`` format, e.g.:
- ``anthropic:claude-3-5-haiku-latest``
- ``openai:gpt-4o-mini``
- ``anthropic:claude-sonnet-4-20250514``
"""

from __future__ import annotations

import json
import os
from functools import cached_property
from pathlib import Path

from observer.constants import OBSERVER_DIR

# Default models — used when no config exists
DEFAULT_SUMMARY_MODEL = "anthropic:claude-3-5-haiku-latest"
DEFAULT_EXTRACTION_MODEL = "anthropic:claude-sonnet-4-20250514"


class Config:
    """File-backed observer configuration with cached reads.

    Reads are cached via ``cached_property`` so repeated access within
    a process doesn't hit disk. Writes invalidate the cache.

    Usage::

        cfg = Config.get()
        cfg.extraction_model          # cached read
        cfg.extraction_model = "..."  # write + invalidate
    """

    _path: Path = OBSERVER_DIR / "config.json"

    def __init__(self) -> None:
        pass

    @classmethod
    def get(cls) -> Config:
        """Return a Config instance."""
        return cls()

    # -- raw I/O --

    @cached_property
    def _data(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text())
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        content = (json.dumps(data, indent=2) + os.linesep).encode()
        fd = os.open(str(self._path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, content)
        finally:
            os.close(fd)
        self._invalidate()

    def _invalidate(self) -> None:
        self.__dict__.pop("_data", None)

    # -- properties --

    @property
    def extraction_model(self) -> str:
        """Configured extraction model (pydantic-ai format)."""
        return self._data.get("extraction_model") or DEFAULT_EXTRACTION_MODEL

    @extraction_model.setter
    def extraction_model(self, value: str) -> None:
        data = dict(self._data)
        data["extraction_model"] = value
        self._write(data)

    @property
    def summary_model(self) -> str:
        """Configured summary model (pydantic-ai format)."""
        return self._data.get("summary_model") or DEFAULT_SUMMARY_MODEL

    @summary_model.setter
    def summary_model(self, value: str) -> None:
        data = dict(self._data)
        data["summary_model"] = value
        self._write(data)

    @property
    def mode(self) -> str:
        """Processing mode: ``'on'`` or ``'off'``."""
        m = self._data.get("mode")
        if m == "off":
            return "off"
        if m in ("on", "full", "lite"):
            return "on"
        # Backward compat: old configs used extraction_enabled boolean
        if "extraction_enabled" in self._data:
            return "on" if self._data["extraction_enabled"] else "off"
        return "on"

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("on", "off"):
            msg = f"Invalid mode: {value!r}. Must be 'on' or 'off'."
            raise ValueError(msg)
        data = dict(self._data)
        data["mode"] = value
        data.pop("extraction_enabled", None)
        self._write(data)
