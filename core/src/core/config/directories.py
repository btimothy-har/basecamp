"""Directory resolution and validation for basecamp."""

from pathlib import Path

from core.exceptions import DirectoryNotFoundError, LauncherError


def resolve_dir(dir_path: str) -> Path:
    """Resolve a home-relative directory path to an absolute path.

    Rejects absolute paths and traversals that escape $HOME.

    Raises:
        LauncherError: If the path is absolute or resolves outside $HOME.
    """
    if Path(dir_path).is_absolute():
        msg = f"Path must be relative to $HOME: {dir_path}"
        raise LauncherError(msg)

    home = Path.home().resolve()
    resolved = (home / dir_path).resolve()

    if not resolved.is_relative_to(home):
        msg = f"Path escapes $HOME: {dir_path}"
        raise LauncherError(msg)

    return resolved


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


def validate_dirs(dirs: list[str]) -> list[Path]:
    """Validate that all directories exist. Returns resolved paths.

    Raises:
        DirectoryNotFoundError: If any directories do not exist or are not directories.
    """
    resolved: list[Path] = []
    errors: list[str] = []

    for dir_path in dirs:
        path = resolve_dir(dir_path)
        if not path.exists():
            errors.append(f"{dir_path} ({path})")
        elif not path.is_dir():
            errors.append(f"{dir_path} ({path}) [not a directory]")
        else:
            resolved.append(path)

    if errors:
        raise DirectoryNotFoundError(errors)

    return resolved
