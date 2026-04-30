"""Directory helpers for basecamp config."""

from pathlib import Path

from basecamp.exceptions import LauncherError


def to_home_relative(path: Path) -> str:
    """Convert an absolute path to a home-relative string for config storage.

    All project directories are stored relative to $HOME.

    Raises:
        LauncherError: If the path is not under the home directory.
    """
    home = Path.home()
    try:
        return str(path.relative_to(home))
    except ValueError:
        msg = f"Path must be under $HOME ({home}): {path}"
        raise LauncherError(msg) from None
