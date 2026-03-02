"""Low-level git repository operations."""

from __future__ import annotations

import subprocess
from pathlib import Path

GIT_TIMEOUT = 30  # Timeout for git operations (seconds)


def is_git_repo(path: Path) -> bool:
    """Check if a path is inside a git repository.

    Args:
        path: Directory path to check.

    Returns:
        True if the path is inside a git repository.
    """
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--git-dir"],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    return result.returncode == 0


def get_repo_name(source_dir: Path) -> str:
    """Get the repository name from a source directory.

    Uses the git toplevel directory name as the repo name.

    Args:
        source_dir: Path to a directory within a git repository.

    Returns:
        The name of the git repository folder.
    """
    result = subprocess.run(
        ["git", "-C", str(source_dir), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    if result.returncode == 0:
        return Path(result.stdout.strip()).name
    # Fallback to directory name if not a git repo
    return source_dir.name


def get_current_branch(path: Path) -> str | None:
    """Get the current branch name for a git repository.

    Args:
        path: Path to a directory within a git repository.

    Returns:
        The current branch name, or None if not on a branch or not a repo.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            check=False,
            cwd=path,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def get_main_branch(path: Path) -> str:
    """Get the main branch name for a git repository.

    Checks for 'main' first, then falls back to 'master'.

    Args:
        path: Path to a directory within a git repository.

    Returns:
        'main' if it exists, 'master' if main doesn't exist, or 'main' as default.
    """
    try:
        check_main = subprocess.run(
            ["git", "rev-parse", "--verify", "main"],
            check=False,
            cwd=path,
            capture_output=True,
            timeout=GIT_TIMEOUT,
        )
        if check_main.returncode == 0:
            return "main"

        check_master = subprocess.run(
            ["git", "rev-parse", "--verify", "master"],
            check=False,
            cwd=path,
            capture_output=True,
            timeout=GIT_TIMEOUT,
        )
        if check_master.returncode == 0:
            return "master"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    return "main"


def get_remote_url(path: Path, remote: str = "origin") -> str | None:
    """Get the URL of a git remote.

    Args:
        path: Path to a directory within a git repository.
        remote: Remote name (default: "origin").

    Returns:
        The remote URL, or None if the remote doesn't exist or not a repo.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", remote],
            check=False,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def resolve_repo_name(project_dirs: list[Path]) -> str | None:
    """Resolve a list of project directories to a repository name.

    Args:
        project_dirs: List of resolved project directories (primary first).

    Returns:
        The repository folder name from the primary directory, or None if not a git repo.
    """
    if not project_dirs:
        return None

    primary_dir = project_dirs[0]

    if not is_git_repo(primary_dir):
        return None

    return get_repo_name(primary_dir)
