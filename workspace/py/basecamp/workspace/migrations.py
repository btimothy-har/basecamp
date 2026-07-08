"""Project configuration migrations for basecamp-workspace."""

from __future__ import annotations

import fcntl
import os
from typing import Any

from basecamp.core.settings import Settings


def migrate_project_dirs_data(data: dict[str, Any]) -> bool:
    """Migrate legacy project ``dirs`` entries to explicit repo fields."""
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


def migrate_project_dirs(settings: Settings) -> bool:
    """Migrate legacy project directory config in a settings file.

    Returns:
        True if the settings file was changed, otherwise False.
    """
    settings.lock_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    lock_fd = os.open(str(settings.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        data = settings._read()
        changed = migrate_project_dirs_data(data)
        if changed:
            settings._write(data)
        return changed
    finally:
        os.close(lock_fd)
