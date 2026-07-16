"""Path constants and helpers for basecamp-core.

Basecamp-owned Python state is rooted under ``~/.pi/basecamp``. This
module owns the root config location plus the user customization dirs
(context/styles/prompts) directly under the Basecamp root; package-specific
runtime state should define its own bounded-context subpaths from that root.
"""

from __future__ import annotations

from pathlib import Path

#: Root pi directory in the user's home.
PI_DIR: Path = Path.home() / ".pi"

#: Basecamp root directory under the pi root.
BASECAMP_CONFIG_DIR: Path = PI_DIR / "basecamp"

#: Default location of the basecamp config file.
DEFAULT_CONFIG_PATH: Path = BASECAMP_CONFIG_DIR / "config.json"

# These override dirs moved out of the former ``workspace/`` subdir to sit
# directly under the Basecamp root. There is no automatic migration: on upgrade,
# users must move any existing files from
# ``~/.pi/basecamp/workspace/{context,styles,prompts}/`` to
# ``~/.pi/basecamp/{context,styles,prompts}/`` by hand.

#: User-supplied context overrides directory.
USER_CONTEXT_DIR: Path = BASECAMP_CONFIG_DIR / "context"

#: User-supplied style overrides directory.
USER_STYLES_DIR: Path = BASECAMP_CONFIG_DIR / "styles"

#: User-supplied prompt fragment overrides directory.
USER_PROMPTS_DIR: Path = BASECAMP_CONFIG_DIR / "prompts"


# --- Hub daemon runtime paths -------------------------------------------------
#
# The hub daemon's runtime state lives under ``~/.pi/basecamp/swarm``. These are
# lazy, ``home``-parameterized helpers (not import-time constants) so tests that
# monkeypatch ``$HOME`` — and the ensure-daemon client — resolve the right paths
# at call time. ``basecamp.hub.store.text.default_db_path`` delegates to
# :func:`daemon_db_path`, keeping the DB location single-sourced.


def swarm_runtime_dir(home: Path | None = None) -> Path:
    """Return the hub daemon's runtime directory (``~/.pi/basecamp/swarm``)."""
    return (home or Path.home()) / ".pi" / "basecamp" / "swarm"


def daemon_socket_path(home: Path | None = None) -> Path:
    """Return the daemon's Unix domain socket path."""
    return swarm_runtime_dir(home) / "daemon.sock"


def daemon_pidfile_path(home: Path | None = None) -> Path:
    """Return the daemon's PID file path."""
    return swarm_runtime_dir(home) / "daemon.pid"


def daemon_spawn_lock_path(home: Path | None = None) -> Path:
    """Return the exclusive-create spawn-lock path used to serialize daemon starts."""
    return swarm_runtime_dir(home) / "daemon.spawn.lock"


def daemon_db_path(home: Path | None = None) -> Path:
    """Return the daemon's SQLite database path."""
    return swarm_runtime_dir(home) / "daemon.db"
