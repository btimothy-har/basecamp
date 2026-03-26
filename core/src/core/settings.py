"""Persistent configuration for basecamp-core.

Stores settings in ~/.basecamp/config.json so they survive across
installations and invocation paths without relying on environment variables.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.utils import atomic_write_json

_DEFAULT_PATH = Path.home() / ".basecamp" / "config.json"

_EXTENDED_CONTEXT_MODELS: dict[str, str] = {
    "sonnet": "sonnet[1m]",
    "opus": "opus[1m]",
}


class Settings:
    """File-backed configuration with locked read-modify-write operations.

    Every property read goes to disk. Every property write acquires an
    exclusive lock, reads the current state, applies the mutation, and
    writes back atomically — preventing lost updates from concurrent access.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _DEFAULT_PATH
        self._lock_path = self._path.with_suffix(".lock")

    @property
    def path(self) -> Path:
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
        atomic_write_json(self._path, data, mode=0o600, dir_mode=0o700)

    @contextmanager
    def _locked_update(self) -> Generator[dict[str, Any], None, None]:
        """Read config under an exclusive lock, yield for mutation, then write back.

        Uses a sibling .lock file so the lock doesn't interfere with
        atomic_write_json's rename-into-place strategy.
        """
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
    def install_dir(self) -> str | None:
        val = self._read().get("install_dir")
        return val if isinstance(val, str) and val.strip() else None

    @install_dir.setter
    def install_dir(self, value: str) -> None:
        with self._locked_update() as data:
            data["install_dir"] = value

    @property
    def projects(self) -> dict[str, Any]:
        projects = self._read().get("projects")
        return projects if isinstance(projects, dict) else {}

    @projects.setter
    def projects(self, value: dict[str, Any]) -> None:
        with self._locked_update() as data:
            data["projects"] = value

    @property
    def logseq_graph(self) -> str | None:
        val = self._read().get("logseq_graph")
        return val if isinstance(val, str) and val.strip() else None

    @logseq_graph.setter
    def logseq_graph(self, value: str) -> None:
        with self._locked_update() as data:
            data["logseq_graph"] = value

    @property
    def use_extended_context(self) -> bool:
        val = self._read().get("use_extended_context")
        return val if isinstance(val, bool) else False

    @use_extended_context.setter
    def use_extended_context(self, value: bool) -> None:
        with self._locked_update() as data:
            data["use_extended_context"] = value

    @property
    def timezone(self) -> str | None:
        val = self._read().get("timezone")
        return val if isinstance(val, str) and val.strip() else None

    @timezone.setter
    def timezone(self, value: str | None) -> None:
        with self._locked_update() as data:
            if value is None:
                data.pop("timezone", None)
            else:
                data["timezone"] = value


settings = Settings()


def resolve_model(model: str) -> str:
    """Apply extended context suffix when enabled in settings.

    Maps base model names to their extended context variants:
    sonnet → sonnet[1m], opus → opus[1m].
    """
    if settings.use_extended_context:
        return _EXTENDED_CONTEXT_MODELS.get(model, model)
    return model
