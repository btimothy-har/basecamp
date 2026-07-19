"""basecamp-core — low-level config primitives shared by basecamp packages.

This package owns low-level Python primitives: exception types, atomic file
helpers, path constants, root install metadata, and a locked JSON settings
store. It also owns the project-configuration schema and its management CLI
(basecamp.core.projects / .model_aliases / .directories / .cli), which the
workspace and CLI shells build on.
"""

from basecamp.core.exceptions import LauncherError
from basecamp.core.files import atomic_write_json
from basecamp.core.paths import (
    BASECAMP_CONFIG_DIR,
    DEFAULT_CONFIG_PATH,
    PI_DIR,
    USER_CONTEXT_DIR,
    USER_PROMPTS_DIR,
    USER_STYLES_DIR,
)
from basecamp.core.settings import Settings, settings

__all__ = [
    "BASECAMP_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "LauncherError",
    "PI_DIR",
    "Settings",
    "USER_CONTEXT_DIR",
    "USER_PROMPTS_DIR",
    "USER_STYLES_DIR",
    "atomic_write_json",
    "settings",
]
