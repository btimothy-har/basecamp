"""Session registration from observer hook input."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeGuard

from pi_observer.data.project import Project
from pi_observer.data.transcript import Transcript
from pi_observer.exceptions import RegistrationError
from pi_observer.services.db import Database

logger = logging.getLogger(__name__)


@dataclass
class HookInput:
    """Parsed SessionStart hook stdin."""

    session_id: str
    transcript_path: str
    cwd: str
    repo_name: str | None = None
    repo_root: str | None = None


@dataclass
class RegistrationResult:
    """Result of a registration operation."""

    project: Project
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


def _is_valid_repo_root(repo_root: Path | None) -> TypeGuard[Path]:
    return (
        repo_root is not None
        and repo_root.is_absolute()
        and repo_root.exists()
        and repo_root.is_dir()
    )


def register_session(hook_input: HookInput) -> RegistrationResult:
    """Upsert project and transcript."""
    repo_root: Path | None = None
    if isinstance(hook_input.repo_root, str) and hook_input.repo_root.strip():
        explicit_repo_root = Path(hook_input.repo_root.strip()).resolve()
        if _is_valid_repo_root(explicit_repo_root):
            repo_root = explicit_repo_root
        else:
            logger.warning(
                "Invalid explicit repo_root %s for session %s; falling back to cwd git inference",
                explicit_repo_root,
                hook_input.session_id,
            )

    if repo_root is None:
        repo_root = resolve_repo_root(hook_input.cwd)
    if not _is_valid_repo_root(repo_root):
        raise RegistrationError(hook_input.cwd)

    if isinstance(hook_input.repo_name, str) and hook_input.repo_name.strip():
        project_name = hook_input.repo_name.strip()
    else:
        project_name = repo_root.name
    repo_path = str(repo_root)

    project = Project.get_by_repo_path(repo_path)
    if project is None:
        project = Project(name=project_name, repo_path=repo_path)
        with Database().session() as session:
            project = project.save(session)

    existing = Transcript.get_by_session_id(hook_input.session_id)
    if existing is not None:
        if existing.ended_at is not None:
            with Database().session() as session:
                existing.ended_at = None
                existing = existing.save(session)
        return RegistrationResult(
            project=project,
            transcript=existing,
            created=False,
        )

    transcript = Transcript(
        project_id=project.id,
        session_id=hook_input.session_id,
        path=hook_input.transcript_path,
        started_at=datetime.now(UTC),
    )
    with Database().session() as session:
        transcript = transcript.save(session)

    return RegistrationResult(
        project=project,
        transcript=transcript,
        created=True,
    )
