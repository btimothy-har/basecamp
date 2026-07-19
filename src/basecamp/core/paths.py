"""Path constants and helpers for basecamp-core.

Basecamp-owned Python state is rooted under ``~/.pi/basecamp``. This
module owns the root config location plus the user context-override dir
directly under the Basecamp root; package-specific runtime state should
define its own bounded-context subpaths from that root.
"""

from __future__ import annotations

from pathlib import Path

#: Root pi directory in the user's home.
PI_DIR: Path = Path.home() / ".pi"

#: Basecamp root directory under the pi root.
BASECAMP_CONFIG_DIR: Path = PI_DIR / "basecamp"

#: Default location of the basecamp config file.
DEFAULT_CONFIG_PATH: Path = BASECAMP_CONFIG_DIR / "config.json"

# The context override dir moved out of the former ``workspace/`` subdir to sit
# directly under the Basecamp root. There is no automatic migration: on upgrade,
# users must move any existing files from ``~/.pi/basecamp/workspace/context/``
# to ``~/.pi/basecamp/context/`` by hand.

#: User-supplied context overrides directory. Injected per-project by the MCP
#: context server (``mcp/resolve.py``) as ``context/<name>.md``.
USER_CONTEXT_DIR: Path = BASECAMP_CONFIG_DIR / "context"
