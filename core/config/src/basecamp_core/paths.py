"""Path constants and helpers for basecamp-core.

These are generic, low-level locations rooted at the user's ``~/.pi``
directory. They intentionally know nothing about project or workspace
schema — that concern belongs to higher-level packages.
"""

from __future__ import annotations

from pathlib import Path

#: Root pi directory in the user's home.
PI_DIR: Path = Path.home() / ".pi"

#: Basecamp config directory under the pi root.
BASECAMP_CONFIG_DIR: Path = PI_DIR / "basecamp"

#: Default location of the basecamp config file.
DEFAULT_CONFIG_PATH: Path = BASECAMP_CONFIG_DIR / "config.json"

#: User-supplied style overrides directory.
USER_STYLES_DIR: Path = PI_DIR / "styles"

#: User-supplied context overrides directory.
USER_CONTEXT_DIR: Path = PI_DIR / "context"
