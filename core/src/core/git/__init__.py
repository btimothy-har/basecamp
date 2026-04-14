"""Git operations for basecamp.

This package consolidates all git-related functionality:
- repo: Low-level git operations (is_git_repo, get_repo_name, etc.)
- worktrees: Worktree management
"""

from core.git.repo import (
    GIT_TIMEOUT,
    get_current_branch,
    get_main_branch,
    get_remote_url,
    get_repo_name,
    is_git_repo,
    resolve_repo_name,
)
from core.git.worktrees import (
    WorktreeInfo,
    attach_worktree,
    create_worktree,
    get_or_create_worktree,
    get_worktree,
    list_all_worktrees,
    list_worktrees,
    remove_all_worktrees,
    remove_worktree,
)

__all__ = [
    # repo
    "GIT_TIMEOUT",
    "get_current_branch",
    "get_main_branch",
    "get_remote_url",
    "get_repo_name",
    "is_git_repo",
    "resolve_repo_name",
    # worktrees
    "WorktreeInfo",
    "attach_worktree",
    "create_worktree",
    "get_or_create_worktree",
    "get_worktree",
    "list_all_worktrees",
    "list_worktrees",
    "remove_all_worktrees",
    "remove_worktree",
]
