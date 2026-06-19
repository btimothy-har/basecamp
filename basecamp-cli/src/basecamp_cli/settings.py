"""Compatibility settings wrapper for basecamp-cli.

Generic settings live in :mod:`basecamp_core.settings`; project-section
migration and accessors are owned by :mod:`basecamp_workspace.migrations`.
"""

from __future__ import annotations

import copy
from typing import Any

from basecamp_core.settings import Settings as _CoreSettings
from basecamp_workspace.migrations import migrate_project_dirs, migrate_project_dirs_data


class Settings(_CoreSettings):
    """Basecamp settings with compatibility project accessors."""

    def migrate_project_dirs(self) -> bool:
        """Migrate legacy project directory config in this settings file."""
        return migrate_project_dirs(self)

    @property
    def projects(self) -> dict[str, Any]:
        self.migrate_project_dirs()
        return self.get_section("projects")

    @projects.setter
    def projects(self, value: dict[str, Any]) -> None:
        def update_projects(data: dict[str, Any]) -> None:
            data["projects"] = copy.deepcopy(value)
            migrate_project_dirs_data(data)

        self.update(update_projects)


settings = Settings()

__all__ = ["Settings", "settings"]
