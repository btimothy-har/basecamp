"""Git worktree management for basecamp."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from core.exceptions import (
    NotAGitRepoError,
    WorktreeCommandError,
    WorktreeCreateFailedError,
    WorktreeNotFoundError,
    WorktreeRemoveFailedError,
)
from core.git.repo import GIT_TIMEOUT, get_repo_name, is_git_repo
from core.utils import atomic_write_json

WORKTREES_DIR = Path.home() / ".worktrees"
WORKTREE_META_DIR = ".meta"


@dataclass
class WorktreeInfo:
    """Information about a git worktree."""

    name: str
    path: Path
    branch: str
    created_at: datetime
    project: str
    repo_name: str
    source_dir: Path = field(default_factory=Path)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "name": self.name,
            "path": str(self.path),
            "branch": self.branch,
            "created_at": self.created_at.isoformat(),
            "project": self.project,
            "repo_name": self.repo_name,
            "source_dir": str(self.source_dir),
        }

    @classmethod
    def from_dict(cls, data: dict) -> WorktreeInfo:
        """Create WorktreeInfo from dictionary."""
        return cls(
            name=data["name"],
            path=Path(data["path"]),
            branch=data["branch"],
            created_at=datetime.fromisoformat(data["created_at"]),
            project=data["project"],
            repo_name=data.get("repo_name", ""),
            source_dir=Path(data.get("source_dir", "")),
        )


def _get_repo_worktrees_dir(repo_name: str) -> Path:
    """Get the worktrees directory for a specific repository."""
    return WORKTREES_DIR / repo_name


def _get_meta_dir(repo_name: str) -> Path:
    """Get the metadata directory for a repository."""
    return _get_repo_worktrees_dir(repo_name) / WORKTREE_META_DIR


def _save_worktree_metadata(info: WorktreeInfo) -> None:
    """Save worktree metadata to a JSON file outside the worktree."""
    meta_path = _get_meta_dir(info.repo_name) / f"{info.name}.json"
    atomic_write_json(meta_path, info.to_dict())


def _load_worktree_metadata(repo_name: str, name: str) -> WorktreeInfo | None:
    """Load worktree metadata from a JSON file."""
    meta_path = _get_meta_dir(repo_name) / f"{name}.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        return WorktreeInfo.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


def _delete_worktree_metadata(repo_name: str, name: str) -> None:
    """Delete worktree metadata file."""
    meta_path = _get_meta_dir(repo_name) / f"{name}.json"
    if meta_path.exists():
        meta_path.unlink()


def create_worktree(
    source_dir: Path,
    project: str,
    label: str,
) -> WorktreeInfo:
    """Create a new git worktree for a project.

    Args:
        source_dir: The source git repository directory.
        project: The project name (stored in metadata).
        label: The label/name for the worktree (used as directory name and branch suffix).

    Returns:
        WorktreeInfo with details about the created worktree.

    Raises:
        WorktreeCommandError: If the git worktree command fails.
    """
    repo_name = get_repo_name(source_dir)
    name = label
    branch = f"wt/{label}"
    worktree_path = _get_repo_worktrees_dir(repo_name) / name

    # Create parent directory
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    # Create the worktree with a new branch
    result = subprocess.run(
        ["git", "-C", str(source_dir), "worktree", "add", "-b", branch, str(worktree_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )

    if result.returncode != 0:
        raise WorktreeCreateFailedError(result.stderr.strip())

    # Create and save metadata
    info = WorktreeInfo(
        name=name,
        path=worktree_path,
        branch=branch,
        created_at=datetime.now(tz=UTC),
        project=project,
        repo_name=repo_name,
        source_dir=source_dir,
    )
    _save_worktree_metadata(info)

    return info


def get_worktree(repo_name: str, name: str) -> WorktreeInfo | None:
    """Get information about a specific worktree.

    Args:
        repo_name: The repository folder name.
        name: The worktree name.

    Returns:
        WorktreeInfo if found, None otherwise.
    """
    worktree_path = _get_repo_worktrees_dir(repo_name) / name
    if not worktree_path.exists():
        return None
    return _load_worktree_metadata(repo_name, name)


def attach_worktree(
    primary_dir: Path,
    name: str,
) -> tuple[Path, WorktreeInfo]:
    """Attach to an existing worktree.

    Args:
        primary_dir: The primary directory of the project (used to determine repo).
        name: The name of the worktree to attach to.

    Returns:
        A tuple of (worktree_path, worktree_info).

    Raises:
        NotAGitRepoError: If primary_dir is not a git repository.
        WorktreeNotFoundError: If the worktree doesn't exist.
    """
    repo_name = get_repo_name(primary_dir) if is_git_repo(primary_dir) else None

    if not repo_name:
        raise NotAGitRepoError(primary_dir)

    worktree_info = get_worktree(repo_name, name)
    if not worktree_info:
        raise WorktreeNotFoundError(repo_name, name)

    return worktree_info.path, worktree_info


def get_or_create_worktree(
    source_dir: Path,
    project: str,
    label: str,
) -> tuple[WorktreeInfo, bool]:
    """Get an existing worktree or create a new one.

    Args:
        source_dir: The source git repository directory.
        project: The project name (stored in metadata).
        label: The label/name for the worktree.

    Returns:
        A tuple of (WorktreeInfo, created) where created is True if a new
        worktree was created, False if an existing one was returned.

    Raises:
        NotAGitRepoError: If source_dir is not a git repository.
        WorktreeCommandError: If worktree creation fails.
    """
    repo_name = get_repo_name(source_dir) if is_git_repo(source_dir) else None

    if not repo_name:
        raise NotAGitRepoError(source_dir)

    # Check if worktree already exists
    existing = get_worktree(repo_name, label)
    if existing:
        return existing, False

    # Create new worktree
    info = create_worktree(source_dir, project, label)
    return info, True


def list_worktrees(repo_name: str) -> list[WorktreeInfo]:
    """List all worktrees for a repository.

    Args:
        repo_name: The repository folder name.

    Returns:
        List of WorktreeInfo for each worktree, sorted by creation time (newest first).
    """
    meta_dir = _get_meta_dir(repo_name)
    if not meta_dir.exists():
        return []

    worktrees: list[WorktreeInfo] = []
    for meta_file in meta_dir.glob("*.json"):
        name = meta_file.stem  # Get worktree name from filename
        info = _load_worktree_metadata(repo_name, name)
        if info:
            # Only include if the worktree directory still exists
            if info.path.exists():
                worktrees.append(info)
            else:
                # Clean up orphaned metadata
                _delete_worktree_metadata(repo_name, name)

    # Sort by creation time, newest first
    worktrees.sort(key=lambda x: x.created_at, reverse=True)
    return worktrees


def list_all_worktrees() -> dict[str, list[WorktreeInfo]]:
    """List all worktrees across all repositories.

    Returns:
        Dictionary mapping repo names to lists of WorktreeInfo, sorted by creation time.
    """
    if not WORKTREES_DIR.exists():
        return {}

    all_worktrees: dict[str, list[WorktreeInfo]] = {}

    for repo_dir in WORKTREES_DIR.iterdir():
        # Skip hidden directories (like .meta)
        if repo_dir.is_dir() and not repo_dir.name.startswith("."):
            repo_name = repo_dir.name
            worktrees = list_worktrees(repo_name)
            if worktrees:
                all_worktrees[repo_name] = worktrees

    return all_worktrees


def remove_worktree(repo_name: str, name: str, *, force: bool = False) -> None:
    """Remove a specific worktree.

    Args:
        repo_name: The repository folder name.
        name: The worktree name.
        force: If True, force removal even with uncommitted changes.

    Raises:
        WorktreeNotFoundError: If the worktree doesn't exist.
        WorktreeCommandError: If the git command fails.
    """
    info = get_worktree(repo_name, name)
    if not info:
        raise WorktreeNotFoundError(repo_name, name)

    if not is_git_repo(info.source_dir):
        if not force:
            msg = f"Source repo no longer exists at {info.source_dir}. Remove manually: rm -rf {info.path}"
            raise WorktreeCommandError(msg)
        if info.path.exists():
            resolved = info.path.resolve()
            if not resolved.is_relative_to(WORKTREES_DIR.resolve()):
                msg = f"Refusing to delete {resolved}: not under {WORKTREES_DIR}"
                raise WorktreeCommandError(msg)
            shutil.rmtree(resolved)
        _delete_worktree_metadata(repo_name, name)
        return

    # Remove the worktree using git
    cmd = ["git", "-C", str(info.source_dir), "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(str(info.path))

    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=GIT_TIMEOUT)

    if result.returncode != 0:
        raise WorktreeRemoveFailedError(result.stderr.strip())

    # Delete the metadata file
    _delete_worktree_metadata(repo_name, name)

    # Delete the branch
    branch_result = subprocess.run(
        ["git", "-C", str(info.source_dir), "branch", "-d" if not force else "-D", info.branch],
        check=False,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
    )
    # Branch deletion failure is not critical
    if branch_result.returncode != 0 and "not found" not in branch_result.stderr.lower():
        pass  # Branch may have been deleted manually or merged


def remove_all_worktrees(repo_name: str, *, force: bool = False) -> list[str]:
    """Remove all worktrees for a repository.

    Args:
        repo_name: The repository folder name.
        force: If True, force removal even with uncommitted changes.

    Returns:
        List of removed worktree names.

    Raises:
        WorktreeCommandError: If any git command fails.
    """
    worktrees = list_worktrees(repo_name)
    removed: list[str] = []

    for info in worktrees:
        try:
            remove_worktree(repo_name, info.name, force=force)
            removed.append(info.name)
        except WorktreeCommandError:  # noqa: PERF203
            if not force:
                raise

    # Clean up the meta directory if empty
    meta_dir = _get_meta_dir(repo_name)
    if meta_dir.exists() and not any(meta_dir.iterdir()):
        meta_dir.rmdir()

    # Clean up the repo directory if empty (only .meta or nothing left)
    repo_dir = _get_repo_worktrees_dir(repo_name)
    if repo_dir.exists() and not any(repo_dir.iterdir()):
        repo_dir.rmdir()

    return removed
