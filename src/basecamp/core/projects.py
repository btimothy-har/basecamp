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

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import CONFIG_VERSION, Settings, settings

PROJECTS_SECTION = "projects"


class ProjectConfig(BaseModel):
    """Configuration for a single project."""

    model_config = ConfigDict(extra="forbid")

    repo_root: str
    additional_dirs: list[str] = Field(default_factory=list)
    description: str = ""
    context: str | None = None


#: Fields removed from ``ProjectConfig`` but tolerated on load so a config.json
#: written by an older basecamp (which seeded ``working_style``) still loads —
#: ``extra="forbid"`` would otherwise reject it. Stripped, not migrated.
_LEGACY_PROJECT_KEYS = ("working_style",)


def load_projects(config: Settings | None = None) -> dict[str, ProjectConfig]:
    """Load project configurations from the ``projects`` section.

    Returns an empty dict if no projects are configured.
    """
    active = config or settings
    raw = active.get_section(PROJECTS_SECTION)
    if not raw:
        return {}
    projects: dict[str, ProjectConfig] = {}
    for name, data in raw.items():
        record = {k: v for k, v in data.items() if k not in _LEGACY_PROJECT_KEYS} if isinstance(data, dict) else data
        try:
            projects[name] = ProjectConfig.model_validate(record)
        except ValidationError as exc:
            detail = exc.errors()[0]["msg"] if exc.errors() else str(exc)
            msg = f"Invalid project '{name}' in config.json: {detail}"
            raise LauncherError(msg) from exc
    return projects


def save_projects(projects: dict[str, ProjectConfig], config: Settings | None = None) -> None:
    """Persist project configurations to the ``projects`` section."""
    active = config or settings
    value = {name: project.model_dump() for name, project in projects.items()}

    def mutate(data: dict[str, Any]) -> None:
        data["version"] = CONFIG_VERSION
        data[PROJECTS_SECTION] = copy.deepcopy(value)

    active.update(mutate)
