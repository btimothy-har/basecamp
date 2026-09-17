"""Conservative cleanup for automatic OMP scratch worktrees."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from basecamp.omp.detached_run import CleanupFailure, remove_workspace
from basecamp.omp.snapshot import WorkspaceSnapshot, matches_disposable_state

_COMMAND_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ScratchCleanupResult:
    """Outcome of deciding whether an automatic scratch is disposable."""

    retained_reason: str | None = None
    failure: CleanupFailure | None = None


def cleanup_automatic_workspace(
    source_root: Path,
    workspace_path: Path,
    snapshot: WorkspaceSnapshot,
) -> ScratchCleanupResult:
    """Remove only an unchanged detached scratch; retain every uncertain state."""
    if not workspace_path.exists():
        return ScratchCleanupResult()

    branch, branch_error = _current_branch(workspace_path)
    if branch_error is not None:
        return ScratchCleanupResult(retained_reason=branch_error)
    if branch is not None:
        return ScratchCleanupResult(retained_reason=f"it is attached to branch {branch}")
    if not matches_disposable_state(snapshot, workspace_path):
        return ScratchCleanupResult(retained_reason="it contains changes, commits, or unverifiable Git state")

    failure = remove_workspace(source_root, workspace_path)
    return ScratchCleanupResult(failure=failure)


def _current_branch(workspace_path: Path) -> tuple[str | None, str | None]:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace_path), "symbolic-ref", "--quiet", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"its branch state could not be inspected: {exc}"
    if result.returncode == 0:
        branch = result.stdout.strip()
        if branch:
            return branch, None
        return None, "its branch state could not be identified"
    if result.returncode == 1:
        return None, None
    detail = result.stderr.strip() or f"git symbolic-ref exited {result.returncode}"
    return None, f"its branch state could not be inspected: {detail}"
