"""Generic file-backed JSON settings with locked read-modify-write.

This module owns a locked JSON settings primitive plus root installer metadata
helpers. It deliberately knows nothing about project or workspace schema — that
concern belongs to higher-level packages built on top of :class:`Settings`.
"""

from __future__ import annotations

import fcntl
import json
import os
import stat
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from basecamp.core.files import atomic_write_json
from basecamp.core.paths import DEFAULT_CONFIG_PATH

CONFIG_VERSION = 1


class Settings:
    """File-backed JSON configuration with locked read-modify-write operations.

    Every read goes to disk. Every write acquires an exclusive lock, reads
    the current state, applies the mutation, and writes back atomically —
    preventing lost updates from concurrent access.

    The stored document is a JSON object (dict). Missing, corrupt, or
    non-dict files are treated as an empty document on read.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or DEFAULT_CONFIG_PATH
        self._lock_path = self._path.with_suffix(".lock")

    @property
    def path(self) -> Path:
        """Path to the backing JSON config file."""
        return self._path

    @property
    def lock_path(self) -> Path:
        """Path to the sibling lock file used for serialised updates."""
        return self._lock_path

    def _read(self) -> dict[str, Any]:
        """Read the config document, returning ``{}`` for missing/corrupt/non-dict files."""
        if not self._path.exists():
            return {}
        try:
            parsed = json.loads(self._path.read_text())
            return parsed if isinstance(parsed, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict[str, Any]) -> None:
        """Write the config document atomically with restrictive permissions."""
        atomic_write_json(self._path, data, mode=0o600, dir_mode=0o700)

    @contextmanager
    def _locked_document(self) -> Generator[dict[str, Any], None, None]:
        """Read config while holding its sibling lock."""
        self._lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            yield self._read()
        finally:
            os.close(lock_fd)

    @contextmanager
    def _locked_update(self) -> Generator[dict[str, Any], None, None]:
        """Read config under an exclusive lock, yield for mutation, then write back.

        Uses a sibling ``.lock`` file so the lock doesn't interfere with
        :func:`basecamp.core.files.atomic_write_json`'s rename-into-place
        strategy.
        """
        with self._locked_document() as data:
            yield data
            self._write(data)

    def update(self, mutator: Callable[[dict[str, Any]], None]) -> None:
        """Apply ``mutator`` to the config document under an exclusive lock.

        The mutator receives the current document dict and may mutate it in
        place; the result is written back atomically.
        """
        with self._locked_update() as data:
            mutator(data)

    def update_if_changed(self, mutator: Callable[[dict[str, Any]], bool]) -> bool:
        """Write only when ``mutator`` reports that it changed the document."""
        with self._locked_document() as data:
            changed = mutator(data)
            if changed:
                self._write(data)
            return changed

    def restrict_permissions(self) -> None:
        """Set the config file to 0600 without following a replacement symlink."""
        with self._locked_document():
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                    msg = f"Config is no longer a regular file: {self._path}"
                    raise OSError(msg)
                os.fchmod(descriptor, 0o600)
            finally:
                os.close(descriptor)

    @property
    def install_dir(self) -> str | None:
        """Configured install directory, or ``None`` if unset/blank."""
        val = self._read().get("install_dir")
        return val if isinstance(val, str) and val.strip() else None

    @install_dir.setter
    def install_dir(self, value: str) -> None:
        with self._locked_update() as data:
            data["version"] = CONFIG_VERSION
            data["install_dir"] = value

    def set_install_metadata(self, *, install_dir: str) -> None:
        """Persist installer-owned root metadata in one locked write.

        Only the installer-owned keys are written; other sections (e.g.
        ``logseq``, ``environments``) are preserved. Stale pre-consolidation
        keys (``installed_modules``) are dropped when present.
        """
        with self._locked_update() as data:
            data["version"] = CONFIG_VERSION
            data["install_dir"] = install_dir
            data.pop("installed_modules", None)

    def read(self) -> dict[str, Any]:
        """Return the full config document (``{}`` for missing/corrupt files)."""
        return self._read()

    def get_section(self, name: str) -> Any:
        """Return a top-level config section, or ``{}`` if missing/non-dict.

        Sections are top-level keys whose value is expected to be a dict.
        Non-dict values (or missing keys) yield an empty dict so callers can
        treat the result uniformly.
        """
        section = self._read().get(name)
        return section if isinstance(section, dict) else {}

    def set_section(self, name: str, value: Any) -> None:
        """Set a top-level config section under an exclusive lock."""
        with self._locked_update() as data:
            data[name] = value


settings = Settings()
