"""Configuration management for basecamp."""

from basecamp_cli.config.project import (
    ProjectConfig,
    load_projects,
    save_projects,
)

__all__ = [
    "ProjectConfig",
    "load_projects",
    "save_projects",
]
