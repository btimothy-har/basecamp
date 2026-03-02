"""Configuration management for basecamp."""

from core.config.directories import resolve_dir, validate_dirs
from core.config.project import (
    Config,
    ProjectConfig,
    load_config,
    resolve_project,
    save_config,
)

__all__ = [
    # Project
    "Config",
    "ProjectConfig",
    "load_config",
    "resolve_project",
    "save_config",
    # Directories
    "resolve_dir",
    "validate_dirs",
]
