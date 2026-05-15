"""Persistent configuration for pi-memory.

Stores memory settings in ~/.pi/memory/config.json.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

from pi_memory.constants import MEMORY_DIR

INTERPRETATION_MODEL_ENV: Final = "PI_MEMORY_INTERPRETATION_MODEL"

_DEFAULT_PATH = MEMORY_DIR / "config.json"
_UNSET = object()


class SettingsError(Exception):
    """Raised when memory settings are invalid."""


class InvalidInterpretationModelError(SettingsError):
    """Raised when an interpretation model value is invalid."""

    def __init__(self) -> None:
        super().__init__("Invalid interpretation model: must be a non-empty string.")


class MissingInterpretationModelError(SettingsError):
    """Raised when session interpretation has no configured model."""

    def __init__(self) -> None:
        super().__init__("interpretation_model is required for session interpretation.")


def _atomic_write_json(
    path: Path,
    data: dict[str, Any],
    *,
    mode: int = 0o600,
    dir_mode: int = 0o700,
) -> None:
    """Write JSON to path atomically."""
    path.parent.mkdir(parents=True, mode=dir_mode, exist_ok=True)
    content = (json.dumps(data, indent=2, sort_keys=True) + os.linesep).encode()
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


def _validate_interpretation_model(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise InvalidInterpretationModelError()


class Settings:
    """File-backed memory configuration with environment overrides."""

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
    def interpretation_model(self) -> str | None:
        """Return the effective interpretation model, including environment overrides."""
        env_value = os.environ.get(INTERPRETATION_MODEL_ENV)
        if env_value is not None:
            return _validate_interpretation_model(env_value)

        value = self._read().get("interpretation_model")
        if value is None:
            return None
        return _validate_interpretation_model(value)

    @interpretation_model.setter
    def interpretation_model(self, value: str) -> None:
        self.update(interpretation_model=value)

    def require_interpretation_model(self) -> str:
        """Return the configured interpretation model or raise a clear setup error."""
        model = self.interpretation_model
        if model is None:
            raise MissingInterpretationModelError()
        return model

    def update(self, *, interpretation_model: str | None | object = _UNSET) -> None:
        """Persist file settings after validating the resulting file configuration."""
        with self._locked_update() as data:
            data.pop("interpreter_mode", None)
            if interpretation_model is _UNSET:
                return
            if interpretation_model is None:
                data.pop("interpretation_model", None)
                return
            data["interpretation_model"] = _validate_interpretation_model(interpretation_model)

    def as_dict(self) -> dict[str, str | None]:
        """Return effective settings with environment overrides applied."""
        return {"interpretation_model": self.interpretation_model}


settings = Settings()
