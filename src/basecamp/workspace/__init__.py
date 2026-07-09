"""Basecamp workspace — per-repo worktree-setup environments.

Project configuration schema moved to basecamp.core (docs/design/repo-rearchitecture.md §6.1).
"""

from basecamp.workspace.environments import (
    ENVIRONMENTS_SECTION,
    EnvironmentConfig,
    get_environment,
    load_environments,
    remove_environment,
    set_environment,
)

__all__ = [
    "ENVIRONMENTS_SECTION",
    "EnvironmentConfig",
    "get_environment",
    "load_environments",
    "remove_environment",
    "set_environment",
]
