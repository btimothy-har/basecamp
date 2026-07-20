"""Filesystem layout for basecamp's ``~/.pi/basecamp`` tree.

Single source for every basecamp-owned path: the config root, the user
override dirs (context/styles/prompts), and the daemon + companion runtime
tree (``swarm/``, ``tasks/``, ``companion/``). Consumers import these constants
instead of re-deriving ``~/.pi/basecamp/<sub>`` by hand — that re-derivation
previously drifted across the hub, the companion, and the doctor (the
``swarm/`` dir alone was spelled in four separate files).

The runtime tree lives here, not in the hub/companion packages, because it is
shared layout knowledge: the daemon writes it, the companion reads part of it,
and ``basecamp doctor`` inspects all of it. Keeping it in ``core`` lets each of
those import the layout without ``core`` importing them.

``basecamp_config_dir()`` / ``swarm_agents_dir()`` rebase the tree onto a
non-default home for the one runtime seam that needs it — a dispatched child
agent whose ``HOME`` differs from the daemon's. ``rebase()`` rebases a default
path onto an arbitrary root, for the doctor's injectable ``Locations``.
"""

from __future__ import annotations

from pathlib import Path

#: Root pi directory in the user's home.
PI_DIR: Path = Path.home() / ".pi"


def basecamp_config_dir(home: str | Path | None = None) -> Path:
    """Return the ``~/.pi/basecamp`` root, optionally under a non-default home."""
    base = Path(home).expanduser() if home is not None else Path.home()
    return base / ".pi" / "basecamp"


#: Basecamp root directory under the pi root.
BASECAMP_CONFIG_DIR: Path = basecamp_config_dir()

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

# ── daemon + companion runtime tree ──

#: Hub daemon runtime root.
SWARM_DIR: Path = BASECAMP_CONFIG_DIR / "swarm"

#: Per-agent run/session state under the daemon root.
SWARM_AGENTS_DIR: Path = SWARM_DIR / "agents"

#: Hub daemon SQLite database.
DAEMON_DB: Path = SWARM_DIR / "daemon.db"

#: Hub daemon Unix domain socket.
DAEMON_SOCK: Path = SWARM_DIR / "daemon.sock"

#: Hub daemon pid file.
DAEMON_PID: Path = SWARM_DIR / "daemon.pid"

#: Task-log directory (per-session task cycles).
TASKS_DIR: Path = BASECAMP_CONFIG_DIR / "tasks"

#: Companion runtime root (snapshots and related state).
COMPANION_DIR: Path = BASECAMP_CONFIG_DIR / "companion"


def swarm_agents_dir(home: str | Path | None = None) -> Path:
    """Return ``swarm/agents`` under an arbitrary home.

    A dispatched child agent may run under a different ``HOME`` than the daemon,
    and its run-result sidecar is written relative to the child's home — so this
    one subtree is parametrized where the constant would be wrong.
    """
    return basecamp_config_dir(home) / SWARM_AGENTS_DIR.relative_to(BASECAMP_CONFIG_DIR)


def rebase(path: Path, root: Path) -> Path:
    """Rebase a default basecamp path onto another root.

    ``rebase(DAEMON_PID, tmp)`` → ``tmp/swarm/daemon.pid``. Used by the doctor's
    injectable ``Locations`` so it resolves the real layout under a temp root
    without re-spelling the segments this module already owns.
    """
    return root / path.relative_to(BASECAMP_CONFIG_DIR)
