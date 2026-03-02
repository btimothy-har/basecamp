"""Git status generation for prompts."""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.git.repo import GIT_TIMEOUT, get_current_branch, get_main_branch


def generate_git_status(primary_dir: Path) -> str | None:
    """Generate git status block for the primary directory.

    Returns None if not a git repo or if git commands fail.
    """
    try:
        # Get current branch
        current_branch = get_current_branch(primary_dir)
        if current_branch is None:
            return None

        # Get main branch
        main_branch = get_main_branch(primary_dir)

        # Get status (short format)
        status_result = subprocess.run(
            ["git", "status", "--short"],
            check=False,
            cwd=primary_dir,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        status = status_result.stdout.strip() if status_result.returncode == 0 else ""

        # Get recent commits
        log_result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            check=False,
            cwd=primary_dir,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
        recent_commits = log_result.stdout.strip() if log_result.returncode == 0 else ""

        lines = [
            "gitStatus: This is the git status at the start of the conversation. "
            "Note that this status is a snapshot in time, and will not update during the conversation.",
            f"Current branch: {current_branch}",
            "",
            f"Main branch (you will usually use this for PRs): {main_branch}",
            "",
            "Status:",
            status if status else "(clean)",
            "",
            "Recent commits:",
            recent_commits,
        ]
        return "\n".join(lines)

    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
