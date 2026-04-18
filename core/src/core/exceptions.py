"""Exception classes for basecamp."""


class LauncherError(Exception):
    """Base exception for basecamp errors."""


class ProjectNotFoundError(LauncherError):
    """Raised when a requested project is not found."""

    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(f"Project '{name}' not found. Available: {', '.join(available)}")


class DirectoryNotFoundError(LauncherError):
    """Raised when required directories do not exist."""

    def __init__(self, dirs: list[str]) -> None:
        lines = "\n".join(f"  - {directory}" for directory in dirs)
        super().__init__(f"The following directories do not exist:\n{lines}")


class NoDirectoriesConfiguredError(LauncherError):
    """Raised when a project has no directories configured."""

    def __init__(self, project_name: str) -> None:
        super().__init__(f"Project '{project_name}' has no directories configured")


class BlockedArgError(LauncherError):
    """Raised when a user passes a flag that basecamp manages."""

    def __init__(self, flag: str) -> None:
        super().__init__(f"Flag '{flag}' is managed by basecamp and cannot be passed through")
