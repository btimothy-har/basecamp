"""Ephemeral launcher metadata and placement safety for OMP scratches."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from basecamp.core.exceptions import LauncherError

PROTECTED_ROOT_ENV = "BASECAMP_PROTECTED_ROOT"
SCRATCH_ROOT_ENV = "BASECAMP_OMP_SCRATCH_ROOT"
INHERITED_WIP_ENV = "BASECAMP_OMP_INHERITED_WIP"

_ENVIRONMENT_KEYS = (
    PROTECTED_ROOT_ENV,
    SCRATCH_ROOT_ENV,
    INHERITED_WIP_ENV,
    "BASECAMP_OMP_STATE_DIR",
    "BASECAMP_OMP_SCOPE",
    "BASECAMP_OMP_WORKSPACE_FILE",
)


def workspace_child_environment(
    base: Mapping[str, str],
    *,
    protected_root: Path | None = None,
    scratch_root: Path | None = None,
    inherited_wip: bool | None = None,
) -> dict[str, str]:
    """Create a child environment without inherited workspace metadata."""
    environment = dict(base)
    for key in _ENVIRONMENT_KEYS:
        environment.pop(key, None)
    if protected_root is not None:
        environment[PROTECTED_ROOT_ENV] = str(protected_root.resolve())
    if scratch_root is not None:
        environment[SCRATCH_ROOT_ENV] = str(scratch_root.resolve())
    if inherited_wip is not None:
        environment[INHERITED_WIP_ENV] = "1" if inherited_wip else "0"
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
