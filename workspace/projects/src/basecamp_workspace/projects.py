"""Project configuration models and loaders for basecamp-workspace."""

from __future__ import annotations

import copy
from typing import Any

from basecamp_core.settings import Settings, settings
from pydantic import BaseModel, ConfigDict, Field

from basecamp_workspace.migrations import migrate_project_dirs, migrate_project_dirs_data


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    additional_dirs: list[str] = Field(default_factory=list)
    description: str = ""
    working_style: str | None = None
    context: str | None = None


def load_projects(config: Settings | None = None) -> dict[str, ProjectConfig]:
    """Load project configurations from config.json.

    Returns an empty dict if no projects are configured.
    """
    active_settings = config or settings
    migrate_project_dirs(active_settings)
    raw = active_settings.get_section("projects")
    if not raw:
        return {}
    return {name: ProjectConfig.model_validate(data) for name, data in raw.items()}


def save_projects(projects: dict[str, ProjectConfig], config: Settings | None = None) -> None:
    """Persist project configurations to config.json."""
    active_settings = config or settings
    value = {name: project.model_dump() for name, project in projects.items()}

    def update_projects(data: dict[str, Any]) -> None:
        data["projects"] = copy.deepcopy(value)
        migrate_project_dirs_data(data)

    active_settings.update(update_projects)
