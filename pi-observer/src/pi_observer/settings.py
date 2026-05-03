"""Persistent configuration for pi-observer.

Stores observer settings in ~/.pi/observer/config.json.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path.home() / ".pi" / "observer" / "config.json"
DEFAULT_EXTRACTION_MODEL = "anthropic:claude-sonnet-4-20250514"
DEFAULT_SUMMARY_MODEL = "anthropic:claude-3-5-haiku-latest"
DEFAULT_MODE = "on"


def _atomic_write_json(
    path: Path,
    data: dict[str, Any],
    *,
    mode: int = 0o600,
    dir_mode: int = 0o700,
) -> None:
    """Write JSON to path atomically."""
    path.parent.mkdir(parents=True, mode=dir_mode, exist_ok=True)
    content = (json.dumps(data, indent=2) + os.linesep).encode()
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        try:
            os.write(fd, content)
            os.fsync(fd)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise

    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


class Settings:
    """File-backed observer configuration with locked updates."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._lock_path = self._path.with_suffix(".lock")

    @property
    def path(self) -> Path:
        """Return the settings file path."""
        return self._path

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text())
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        _atomic_write_json(self._path, data)

    @contextmanager
    def _locked_update(self) -> Generator[dict[str, Any], None, None]:
        self._lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = self._read()
            yield data
            self._write(data)
        finally:
            os.close(lock_fd)

    @property
    def extraction_model(self) -> str:
        value = self._read().get("extraction_model")
        return value if isinstance(value, str) and value else DEFAULT_EXTRACTION_MODEL

    @extraction_model.setter
    def extraction_model(self, value: str) -> None:
        with self._locked_update() as data:
            data["extraction_model"] = value

    @property
    def summary_model(self) -> str:
        value = self._read().get("summary_model")
        return value if isinstance(value, str) and value else DEFAULT_SUMMARY_MODEL

    @summary_model.setter
    def summary_model(self, value: str) -> None:
        with self._locked_update() as data:
            data["summary_model"] = value

    @property
    def mode(self) -> str:
        value = self._read().get("mode")
        return "off" if value == "off" else DEFAULT_MODE

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("on", "off"):
            msg = f"Invalid mode: {value!r}. Must be 'on' or 'off'."
            raise ValueError(msg)
        with self._locked_update() as data:
            data["mode"] = value

    def as_dict(self) -> dict[str, str]:
        """Return effective settings with defaults applied."""
        return {
            "mode": self.mode,
            "extraction_model": self.extraction_model,
            "summary_model": self.summary_model,
        }


settings = Settings()
