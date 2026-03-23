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


class PromptNotFoundError(LauncherError):
    """Raised when a required prompt file is not found."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Prompt file not found: {path}")


class NoDirectoriesConfiguredError(LauncherError):
    """Raised when a project has no directories configured."""

    def __init__(self, project_name: str) -> None:
        super().__init__(f"Project '{project_name}' has no directories configured")


class PathLaunchLabelError(LauncherError):
    """Raised when worktree labels are used with path-based launch."""

    def __init__(self) -> None:
        super().__init__("Worktree labels (-l) are not supported with path-based launch")


class BlockedArgError(LauncherError):
    """Raised when a user passes a Claude CLI arg that basecamp controls."""

    def __init__(self, arg: str) -> None:
        super().__init__(f"{arg} is managed by basecamp and cannot be passed through")


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


class LogseqNotConfiguredError(LauncherError):
    """Raised when logseq_graph is not set in settings."""

    def __init__(self) -> None:
        super().__init__("Logseq graph not configured. Run: basecamp setup")


class LogseqGraphNotFoundError(LauncherError):
    """Raised when the configured Logseq graph directory does not exist."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Logseq graph directory not found: {path}")


class TaskError(LauncherError):
    """Base exception for task-related errors."""


class NoMultiplexerError(TaskError):
    """Raised when a task dispatch is attempted outside any terminal multiplexer."""

    def __init__(self) -> None:
        super().__init__("task dispatch requires a terminal multiplexer ($KITTY_LISTEN_ON or $TMUX not set)")


class PaneLaunchError(TaskError):
    """Raised when spawning a new terminal pane fails."""

    def __init__(self, backend: str, stderr: str | None = None) -> None:
        msg = f"{backend} pane launch failed"
        if stderr:
            msg = f"{msg}: {stderr}"
        super().__init__(msg)


class TaskNotFoundError(TaskError):
    """Raised when a task does not exist in the index."""

    def __init__(self, name: str, project: str) -> None:
        super().__init__(f"Task {name!r} not found for project {project!r}")


class InvalidTaskNameError(TaskError):
    """Raised when a task name contains unsafe characters."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"Invalid task name {name!r}"
            " — must start with an alphanumeric and contain only alphanumerics, hyphens, underscores, or dots"
        )


class SessionIdNotSetError(TaskError):
    """Raised when CLAUDE_SESSION_ID is not set in the environment."""

    def __init__(self) -> None:
        super().__init__("CLAUDE_SESSION_ID is not set — task commands must be run from within a Claude session")


class ProjectNotSetError(TaskError):
    """Raised when BASECAMP_PROJECT is not set in the environment."""

    def __init__(self) -> None:
        super().__init__("BASECAMP_PROJECT is not set — task commands must be run from within a Claude session")
