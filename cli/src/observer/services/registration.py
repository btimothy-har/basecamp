"""Session registration — upserts project/worktree/transcript from hook input."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from observer.data.project import Project
from observer.data.transcript import Transcript
from observer.data.worktree import Worktree
from observer.exceptions import RegistrationError
from observer.services.db import Database

logger = logging.getLogger(__name__)

WORKTREES_DIR = Path.home() / ".worktrees"


@dataclass
class HookInput:
    """Parsed SessionStart hook stdin."""

    session_id: str
    transcript_path: str
    cwd: str


@dataclass
class RegistrationResult:
    """Result of a registration operation."""

    project: Project
    worktree: Worktree | None
    transcript: Transcript
    created: bool


def resolve_repo_root(cwd: str) -> Path | None:
    """Resolve the main git repo root from a working directory.

    Uses --git-common-dir to find the shared .git directory, which points to
    the main repo even when inside a worktree.
    """
    try:
        toplevel = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if toplevel.returncode != 0:
            return None

        toplevel_path = Path(toplevel.stdout.strip()).resolve()

        common = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--git-common-dir"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if common.returncode != 0:
            return toplevel_path

        common_dir = Path(common.stdout.strip())
        if not common_dir.is_absolute():
            common_dir = (toplevel_path / common_dir).resolve()
        else:
            common_dir = common_dir.resolve()

        return common_dir.parent  # noqa: TRY300
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def detect_worktree(cwd: str) -> tuple[str, str, str] | None:
    """Detect if cwd is inside a basecamp worktree.

    Returns (label, path, branch) if cwd is under ~/.worktrees/<repo>/<label>/,
    otherwise None.
    """
    try:
        cwd_path = Path(cwd).resolve()
        worktrees_resolved = WORKTREES_DIR.resolve()

        if not cwd_path.is_relative_to(worktrees_resolved):
            return None

        relative = cwd_path.relative_to(worktrees_resolved)
        parts = relative.parts
        if len(parts) < 2:
            return None

        label = parts[1]
        worktree_path = str(worktrees_resolved / parts[0] / label)
        branch = f"wt/{label}"
        return label, worktree_path, branch  # noqa: TRY300
    except (ValueError, IndexError):
        return None


def register_session(hook_input: HookInput) -> RegistrationResult:
    """Upsert project, worktree (if applicable), and transcript."""
    repo_root = resolve_repo_root(hook_input.cwd)
    if repo_root is None:
        raise RegistrationError(hook_input.cwd)

    project_name = repo_root.name
    repo_path = str(repo_root)

    # Upsert project
    project = Project.get_by_repo_path(repo_path)
    if project is None:
        project = Project(name=project_name, repo_path=repo_path)
        with Database().session() as session:
            project = project.save(session)

    # Detect and upsert worktree
    worktree: Worktree | None = None
    wt_info = detect_worktree(hook_input.cwd)
    if wt_info is not None and project.id is not None:
        label, wt_path, branch = wt_info
        worktree = Worktree.get_by_project_and_label(project.id, label)
        if worktree is None:
            worktree = Worktree(
                project_id=project.id,
                label=label,
                path=wt_path,
                branch=branch,
            )
            with Database().session() as session:
                worktree = worktree.save(session)

    # Upsert transcript (idempotent on session_id)
    existing = Transcript.get_by_session_id(hook_input.session_id)
    if existing is not None:
        if existing.ended_at is not None:
            with Database().session() as session:
                existing.ended_at = None
                existing = existing.save(session)
        return RegistrationResult(
            project=project,
            worktree=worktree,
            transcript=existing,
            created=False,
        )

    transcript = Transcript(
        project_id=project.id,
        worktree_id=worktree.id if worktree else None,
        session_id=hook_input.session_id,
        path=hook_input.transcript_path,
        started_at=datetime.now(UTC),
    )
    with Database().session() as session:
        transcript = transcript.save(session)

    return RegistrationResult(
        project=project,
        worktree=worktree,
        transcript=transcript,
        created=True,
    )
