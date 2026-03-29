"""Per-project task index with file locking and self-pruning.

Stores task metadata in ~/.basecamp/tasks/{project}.json. Entries whose
task directories no longer exist (e.g. after reboot) are silently pruned
on every read.
"""

from __future__ import annotations

import fcntl
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import TypeAdapter

from core.constants import TASKS_INDEX_DIR
from core.task.models import TaskEntry
from core.utils import atomic_write_json

_TASK_LIST_ADAPTER = TypeAdapter(list[TaskEntry])


class TaskIndex:
    """File-backed per-project task index with locked read-modify-write."""

    def __init__(self, project: str) -> None:
        self._project = project
        self._path = TASKS_INDEX_DIR / f"{project}.json"
        self._lock_path = self._path.with_suffix(".lock")

    def _read_raw(self) -> list[TaskEntry]:
        """Read index from disk without pruning.

        Raises on corrupt files (bad JSON, invalid schema) so callers fail
        loudly rather than silently overwriting lost data.
        """
        if not self._path.exists():
            return []
        raw = self._path.read_text()
        return _TASK_LIST_ADAPTER.validate_json(raw)

    def _prune(self, entries: list[TaskEntry]) -> list[TaskEntry]:
        """Drop entries whose task_dir no longer exists."""
        return [e for e in entries if Path(e.task_dir).is_dir()]

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """Acquire an exclusive file lock for the duration of the block."""
        self._lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            os.close(lock_fd)

    def read(self) -> list[TaskEntry]:
        """Read the index, pruning stale entries."""
        with self._lock():
            entries = self._read_raw()
            pruned = self._prune(entries)
            if len(pruned) != len(entries):
                self._write(pruned)
            return pruned

    def _write(self, entries: list[TaskEntry]) -> None:
        """Write entries to disk atomically."""
        data = _TASK_LIST_ADAPTER.dump_python(entries, mode="json")
        atomic_write_json(self._path, data, mode=0o600, dir_mode=0o700)

    def add(self, entry: TaskEntry) -> None:
        """Add a task entry to the index."""
        with self._lock():
            entries = self._prune(self._read_raw())
            entries.append(entry)
            self._write(entries)

    _UPDATABLE_FIELDS = frozenset({"status", "closed_at"})

    def update(self, name: str, **fields: object) -> TaskEntry | None:
        """Update fields on an existing entry by name. Returns updated entry or None."""
        invalid = set(fields) - self._UPDATABLE_FIELDS
        if invalid:
            msg = f"Cannot update fields: {invalid}"
            raise ValueError(msg)

        with self._lock():
            entries = self._prune(self._read_raw())
            for entry in entries:
                if entry.name == name:
                    for key, value in fields.items():
                        setattr(entry, key, value)
                    self._write(entries)
                    return entry
            return None

    def remove(self, name: str) -> bool:
        """Remove a task entry by name. Returns True if found and removed."""
        with self._lock():
            entries = self._prune(self._read_raw())
            before = len(entries)
            entries = [e for e in entries if e.name != name]
            if len(entries) < before:
                self._write(entries)
                return True
            return False

    def get(self, name: str) -> TaskEntry | None:
        """Get a single task entry by name."""
        for entry in self.read():
            if entry.name == name:
                return entry
        return None
