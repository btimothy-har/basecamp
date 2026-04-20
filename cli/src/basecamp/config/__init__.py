"""Configuration management for basecamp."""

from basecamp.config.directories import resolve_dir, validate_dirs
from basecamp.config.project import (
    ProjectConfig,
    load_projects,
    resolve_project,
    save_projects,
)

__all__ = [
    # Project
    "ProjectConfig",
    "load_projects",
    "resolve_project",
    "save_projects",
    # Directories
    "resolve_dir",
    "validate_dirs",
]
