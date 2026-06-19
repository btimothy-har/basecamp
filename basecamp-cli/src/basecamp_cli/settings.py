"""Persistent configuration for basecamp.

Stores settings in ``~/.pi/basecamp/config.json`` so they survive across
installations and invocation paths without relying on environment variables.

Generic, schema-agnostic behaviour (locked JSON read/write, ``install_dir``,
sections) is inherited from :class:`basecamp_core.settings.Settings`. This
module layers the project/workspace-specific concerns (the ``projects``
section and the legacy ``dirs`` migration) on top, so project schema stays
out of ``basecamp_core``.
"""

from __future__ import annotations

import copy
import fcntl
import os
from typing import Any

from basecamp_core.settings import Settings as _CoreSettings


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


class Settings(_CoreSettings):
    """Basecamp settings with the project section and legacy ``dirs`` migration.

    Inherits generic locked JSON read/write from
    :class:`basecamp_core.settings.Settings` and adds project-schema-specific
    behaviour that must remain outside ``basecamp_core``.
    """

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


settings = Settings()
