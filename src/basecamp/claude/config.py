"""File-backed JSON config for the basecamp Claude foundation.

A minimal, self-contained parallel to ``basecamp.core.settings`` — it does not
import that module and points at ``~/.claude/basecamp.json`` instead of the
``~/.pi`` config. Every read hits disk; every write takes an exclusive lock,
re-reads, mutates, and writes back atomically (via the shared low-level
:func:`atomic_write_json` file primitive), preventing lost updates.

The stored document is a JSON object. Missing, corrupt, or non-dict files read
as an empty document, so callers can treat the result uniformly.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from basecamp.claude.paths import config_path
from basecamp.core.files import atomic_write_json


class ClaudeConfig:
    """Locked read-modify-write access to ``~/.claude/basecamp.json``."""

    def __init__(self, path: Path | None = None, *, home: Path | None = None) -> None:
        self._path = path or config_path(home)
        self._lock_path = self._path.with_suffix(".lock")

    @property
    def path(self) -> Path:
        """Path to the backing JSON config file."""
        return self._path

    def read(self) -> dict[str, Any]:
        """Return the full config document (``{}`` for missing/corrupt/non-dict files)."""
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def get_section(self, name: str) -> dict[str, Any]:
        """Return a top-level section dict, or ``{}`` if missing/non-dict."""
        section = self.read().get(name)
        return section if isinstance(section, dict) else {}

    @contextmanager
    def _locked_update(self) -> Generator[dict[str, Any], None, None]:
        """Read under an exclusive lock, yield for mutation, then write back atomically."""
        self._lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = self.read()
            yield data
            atomic_write_json(self._path, data, mode=0o600, dir_mode=0o700)
        finally:
            os.close(lock_fd)

    def set_section(self, name: str, value: dict[str, Any]) -> None:
        """Set a top-level section under an exclusive lock."""
        with self._locked_update() as data:
            data[name] = value
