"""Basecamp workspace project configuration."""

from basecamp.workspace.environments import (
    ENVIRONMENTS_SECTION,
    EnvironmentConfig,
    get_environment,
    load_environments,
    remove_environment,
    set_environment,
)
from basecamp.workspace.projects import (
    DEFAULT_PROJECTS_PATH,
    ProjectConfig,
    load_projects,
    projects_settings,
    save_projects,
)

__all__ = [
    "DEFAULT_PROJECTS_PATH",
    "ENVIRONMENTS_SECTION",
    "EnvironmentConfig",
    "ProjectConfig",
    "get_environment",
    "load_environments",
    "load_projects",
    "projects_settings",
    "remove_environment",
    "save_projects",
    "set_environment",
]
