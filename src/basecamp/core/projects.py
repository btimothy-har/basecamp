"""Project configuration models and loaders for basecamp.

Projects live in the ``projects`` section of the root
``~/.pi/basecamp/config.json``. The root :data:`settings` singleton is the sole
writer (flock'd read-modify-write); the Pi extension reads the section
in-process. Other top-level sections (``environments``, ``model_aliases``, …)
are preserved on every write.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from basecamp.core.settings import CONFIG_VERSION, Settings, settings

PROJECTS_SECTION = "projects"


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    additional_dirs: list[str] = Field(default_factory=list)
    description: str = ""
    working_style: str | None = None
    context: str | None = None


def load_projects(config: Settings | None = None) -> dict[str, ProjectConfig]:
    """Load project configurations from the ``projects`` section.

    Returns an empty dict if no projects are configured.
    """
    active = config or settings
    raw = active.get_section(PROJECTS_SECTION)
    if not raw:
        return {}
    return {name: ProjectConfig.model_validate(data) for name, data in raw.items()}


def save_projects(projects: dict[str, ProjectConfig], config: Settings | None = None) -> None:
    """Persist project configurations to the ``projects`` section."""
    active = config or settings
    value = {name: project.model_dump() for name, project in projects.items()}

    def mutate(data: dict[str, Any]) -> None:
        data["version"] = CONFIG_VERSION
        data[PROJECTS_SECTION] = copy.deepcopy(value)

    active.update(mutate)
