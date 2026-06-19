"""Exception classes for basecamp.

Re-exports the shared :class:`basecamp_core.exceptions.LauncherError` so
existing ``basecamp_cli`` imports keep working during the package split.
"""

from basecamp_core.exceptions import LauncherError

__all__ = ["LauncherError"]
