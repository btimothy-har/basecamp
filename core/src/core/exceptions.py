"""Exception classes for the basecamp launcher."""

from pathlib import Path


class LauncherError(Exception):
    """Base exception for launcher errors."""


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


class WorktreeError(LauncherError):
    """Base exception for worktree-related errors."""


class NotAGitRepoError(WorktreeError):
    """Raised when a directory is not a git repository."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Not a git repository: {path}")


class WorktreeNotFoundError(WorktreeError):
    """Raised when attempting to attach to a non-existent worktree."""

    def __init__(self, repo_name: str, name: str) -> None:
        super().__init__(f"Worktree '{name}' not found for repo '{repo_name}'")


class WorktreeCommandError(WorktreeError):
    """Raised when a git worktree command fails."""

    def __init__(self, message: str, stderr: str | None = None) -> None:
        full_message = message
        if stderr:
            full_message = f"{message}: {stderr}"
        super().__init__(full_message)


class WorktreeCreateFailedError(WorktreeCommandError):
    """Raised when the git worktree create command fails."""

    def __init__(self, stderr: str | None = None) -> None:
        super().__init__("Failed to create worktree", stderr)


class WorktreeRemoveFailedError(WorktreeCommandError):
    """Raised when the git worktree remove command fails."""

    def __init__(self, stderr: str | None = None) -> None:
        super().__init__("Failed to remove worktree", stderr)



