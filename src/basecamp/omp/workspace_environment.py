"""Managed child environments and placement safety for OMP scratches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from basecamp.core.exceptions import LauncherError

_GIT_LOCATION_KEYS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_WORK_TREE",
)


def clear_git_location_environment(base: Mapping[str, str]) -> dict[str, str]:
    """Remove inherited variables that redirect Git away from an owned workspace."""
    environment = dict(base)
    for key in _GIT_LOCATION_KEYS:
        environment.pop(key, None)
    return environment


def require_safe_snapshot_paths(
    *,
    snapshot_dir: Path,
    session_dir: Path | None,
    canonical_root: Path,
    worktree_base: Path,
) -> None:
    """Reject snapshot or session placement that cleanup could corrupt."""
    snapshot = resolving_parents(snapshot_dir)
    canonical = resolving_parents(canonical_root)
    worktrees = resolving_parents(worktree_base)
    _require_disjoint("snapshot directory", snapshot, "canonical checkout", canonical)
    _require_disjoint("snapshot directory", snapshot, "worktree base", worktrees)
    if session_dir is None:
        return
    sessions = resolving_parents(session_dir)
    _require_disjoint("session directory", sessions, "canonical checkout", canonical)
    _require_disjoint("session directory", sessions, "snapshot directory", snapshot)


def require_safe_workspace_path(
    *,
    workspace_path: Path,
    snapshot_dir: Path,
    session_dir: Path | None,
    canonical_root: Path,
) -> None:
    """Reject a reserved scratch that overlaps protected or retained state."""
    workspace = resolving_parents(workspace_path)
    _require_disjoint(
        "scratch worktree",
        workspace,
        "canonical checkout",
        resolving_parents(canonical_root),
    )
    _require_disjoint(
        "scratch worktree",
        workspace,
        "snapshot directory",
        resolving_parents(snapshot_dir),
    )
    if session_dir is not None:
        _require_disjoint(
            "scratch worktree",
            workspace,
            "session directory",
            resolving_parents(session_dir),
        )


def resolving_parents(path: Path) -> Path:
    """Resolve a path through its nearest existing parent."""
    current = path
    missing: list[str] = []
    try:
        while not current.exists():
            missing.append(current.name)
            parent = current.parent
            if parent == current:
                break
            current = parent
        resolved = current.resolve()
    except (OSError, RuntimeError) as exc:
        message = f"Could not resolve workspace path {path}: {exc}"
        raise LauncherError(message) from exc
    for name in reversed(missing):
        resolved /= name
    return resolved


def _require_disjoint(first_label: str, first: Path, second_label: str, second: Path) -> None:
    if first.is_relative_to(second) or second.is_relative_to(first):
        message = f"{first_label} must be disjoint from the {second_label} {second}: {first}"
        raise LauncherError(message)
