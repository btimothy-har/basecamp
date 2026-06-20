"""Generic file-backed JSON settings with locked read-modify-write.

This module owns a locked JSON settings primitive plus root installer metadata
helpers. It deliberately knows nothing about project or workspace schema — that
concern belongs to higher-level packages built on top of :class:`Settings`.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from basecamp_core.files import atomic_write_json
from basecamp_core.paths import DEFAULT_CONFIG_PATH

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
    def _locked_update(self) -> Generator[dict[str, Any], None, None]:
        """Read config under an exclusive lock, yield for mutation, then write back.

        Uses a sibling ``.lock`` file so the lock doesn't interfere with
        :func:`basecamp_core.files.atomic_write_json`'s rename-into-place
        strategy.
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

    def update(self, mutator: Callable[[dict[str, Any]], None]) -> None:
        """Apply ``mutator`` to the config document under an exclusive lock.

        The mutator receives the current document dict and may mutate it in
        place; the result is written back atomically.
        """
        with self._locked_update() as data:
            mutator(data)

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

    @staticmethod
    def _normalize_modules(values: Iterable[object]) -> list[str]:
        """Strip, drop blanks/non-strings, and deduplicate module ids."""
        modules: list[str] = []
        seen: set[str] = set()
        for value in values:
            if not isinstance(value, str):
                continue
            module = value.strip()
            if not module or module in seen:
                continue
            modules.append(module)
            seen.add(module)
        return modules

    @property
    def installed_modules(self) -> tuple[str, ...]:
        """Installed Basecamp module ids from the root config."""
        val = self._read().get("installed_modules")
        if not isinstance(val, list):
            return ()
        return tuple(self._normalize_modules(val))

    @installed_modules.setter
    def installed_modules(self, values: Iterable[str]) -> None:
        modules = self._normalize_modules(values)

        with self._locked_update() as data:
            data["version"] = CONFIG_VERSION
            data["installed_modules"] = modules

    def set_install_metadata(self, *, install_dir: str, installed_modules: Iterable[str]) -> None:
        """Persist installer-owned root metadata in one locked write."""
        modules = self._normalize_modules(installed_modules)

        with self._locked_update() as data:
            data.clear()
            data["version"] = CONFIG_VERSION
            data["install_dir"] = install_dir
            data["installed_modules"] = modules

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
