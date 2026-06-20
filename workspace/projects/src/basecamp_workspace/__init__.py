"""Basecamp workspace project configuration."""

from basecamp_workspace.projects import (
    DEFAULT_PROJECTS_PATH,
    ProjectConfig,
    load_projects,
    projects_settings,
    save_projects,
)

__all__ = [
    "DEFAULT_PROJECTS_PATH",
    "ProjectConfig",
    "load_projects",
    "projects_settings",
    "save_projects",
]
