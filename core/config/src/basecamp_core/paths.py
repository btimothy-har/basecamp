"""Path constants and helpers for basecamp-core.

Basecamp-owned Python state is rooted under ``~/.pi/basecamp``. This
module owns the root config location plus Python-visible workspace
customization paths; package-specific runtime state should define its own
bounded-context subpaths from the Basecamp root.
"""

from __future__ import annotations

from pathlib import Path

#: Root pi directory in the user's home.
PI_DIR: Path = Path.home() / ".pi"

#: Basecamp root directory under the pi root.
BASECAMP_CONFIG_DIR: Path = PI_DIR / "basecamp"

#: Default location of the basecamp config file.
DEFAULT_CONFIG_PATH: Path = BASECAMP_CONFIG_DIR / "config.json"

#: Workspace customization directory under the Basecamp root.
BASECAMP_WORKSPACE_DIR: Path = BASECAMP_CONFIG_DIR / "workspace"

#: User-supplied context overrides directory.
USER_CONTEXT_DIR: Path = BASECAMP_WORKSPACE_DIR / "context"

#: User-supplied style overrides directory.
USER_STYLES_DIR: Path = BASECAMP_WORKSPACE_DIR / "styles"

#: User-supplied prompt fragment overrides directory.
USER_PROMPTS_DIR: Path = BASECAMP_WORKSPACE_DIR / "prompts"
