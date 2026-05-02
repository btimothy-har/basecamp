"""Persistent configuration for basecamp-core.

Stores settings in ~/.pi/basecamp/config.json so they survive across
installations and invocation paths without relying on environment variables.
"""

from __future__ import annotations

import copy
import fcntl
import json
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from basecamp.utils import atomic_write_json

_DEFAULT_PATH = Path.home() / ".pi" / "basecamp" / "config.json"


def _migrate_project_dirs(data: dict[str, Any]) -> bool:
    """Migrate legacy project ``dirs`` entries to explicit repo fields.

    Mirrors install.py's standalone migration because install.py cannot rely
    on importing the package before installation.
    """
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return False

    changed = False
    for project in projects.values():
        if not isinstance(project, dict) or "dirs" not in project:
            continue

        dirs = project["dirs"]
        has_repo_root = isinstance(project.get("repo_root"), str) and bool(project["repo_root"])
        has_additional_dirs = isinstance(project.get("additional_dirs"), list)
        if has_repo_root and has_additional_dirs:
            project.pop("dirs")
            changed = True
            continue

        if not isinstance(dirs, list) or not all(isinstance(item, str) for item in dirs):
            continue
        if not has_repo_root and not dirs:
            continue

        if not has_repo_root:
            project["repo_root"] = dirs[0]
        if not has_additional_dirs:
            project["additional_dirs"] = dirs[1:]
        project.pop("dirs")
        changed = True

    return changed


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

    def migrate_project_dirs(self) -> bool:
        """Migrate legacy project directory config in this settings file.

        Returns:
            True if the settings file was changed, otherwise False.
        """
        self._lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        lock_fd = os.open(str(self._lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            data = self._read()
            changed = _migrate_project_dirs(data)
            if changed:
                self._write(data)
            return changed
        finally:
            os.close(lock_fd)

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
        self.migrate_project_dirs()
        projects = self._read().get("projects")
        return projects if isinstance(projects, dict) else {}

    @projects.setter
    def projects(self, value: dict[str, Any]) -> None:
        with self._locked_update() as data:
            data["projects"] = copy.deepcopy(value)
            _migrate_project_dirs(data)

    @property
    def logseq_graph(self) -> str | None:
        val = self._read().get("logseq_graph")
        return val if isinstance(val, str) and val.strip() else None

    @logseq_graph.setter
    def logseq_graph(self, value: str) -> None:
        with self._locked_update() as data:
            data["logseq_graph"] = value

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

    @property
    def language(self) -> str | None:
        val = self._read().get("language")
        return val if isinstance(val, str) and val.strip() else None

    @language.setter
    def language(self, value: str | None) -> None:
        with self._locked_update() as data:
            if value is None:
                data.pop("language", None)
            else:
                data["language"] = value

    @property
    def pi_command(self) -> str | None:
        val = self._read().get("pi_command")
        return val if isinstance(val, str) and val.strip() else None

    @pi_command.setter
    def pi_command(self, value: str | None) -> None:
        with self._locked_update() as data:
            if value is None:
                data.pop("pi_command", None)
            else:
                data["pi_command"] = value

    @property
    def models(self) -> dict[str, str]:
        models = self._read().get("models")
        return models if isinstance(models, dict) else {}

    @models.setter
    def models(self, value: dict[str, str]) -> None:
        with self._locked_update() as data:
            if value:
                data["models"] = value
            else:
                data.pop("models", None)

    @property
    def bigquery(self) -> dict[str, Any]:
        bigquery = self._read().get("bigquery")
        return bigquery if isinstance(bigquery, dict) else {}

    @bigquery.setter
    def bigquery(self, value: dict[str, Any] | None) -> None:
        with self._locked_update() as data:
            if value:
                data["bigquery"] = value
            else:
                data.pop("bigquery", None)

    @property
    def worktree_branch_prefix(self) -> str | None:
        val = self._read().get("worktree_branch_prefix")
        return val if isinstance(val, str) and val.strip() else None

    @worktree_branch_prefix.setter
    def worktree_branch_prefix(self, value: str | None) -> None:
        with self._locked_update() as data:
            if value is None:
                data.pop("worktree_branch_prefix", None)
            else:
                data["worktree_branch_prefix"] = value

    # --- observer config (nested) ---

    @property
    def observer(self) -> ObserverConfig:
        return ObserverConfig(self)


class ObserverConfig:
    """Observer config namespace — reads/writes through parent Settings.

    Access via ``settings.observer.extraction_model`` etc.
    All I/O is delegated to the parent's locked read/write.
    """

    DEFAULT_EXTRACTION_MODEL = "anthropic:claude-sonnet-4-20250514"
    DEFAULT_SUMMARY_MODEL = "anthropic:claude-3-5-haiku-latest"

    def __init__(self, parent: Settings) -> None:
        self._parent = parent

    def _data(self) -> dict[str, Any]:
        obs = self._parent._read().get("observer")
        return obs if isinstance(obs, dict) else {}

    @property
    def is_configured(self) -> bool:
        """Whether observer has been explicitly configured."""
        return bool(self._data())

    @property
    def extraction_model(self) -> str:
        return self._data().get("extraction_model") or self.DEFAULT_EXTRACTION_MODEL

    @extraction_model.setter
    def extraction_model(self, value: str) -> None:
        with self._parent._locked_update() as data:
            data.setdefault("observer", {})["extraction_model"] = value

    @property
    def summary_model(self) -> str:
        return self._data().get("summary_model") or self.DEFAULT_SUMMARY_MODEL

    @summary_model.setter
    def summary_model(self, value: str) -> None:
        with self._parent._locked_update() as data:
            data.setdefault("observer", {})["summary_model"] = value

    @property
    def mode(self) -> str:
        """Processing mode: 'on' or 'off'."""
        m = self._data().get("mode")
        if m == "off":
            return "off"
        return "on"

    @mode.setter
    def mode(self, value: str) -> None:
        if value not in ("on", "off"):
            msg = f"Invalid mode: {value!r}. Must be 'on' or 'off'."
            raise ValueError(msg)
        with self._parent._locked_update() as data:
            data.setdefault("observer", {})["mode"] = value


settings = Settings()
