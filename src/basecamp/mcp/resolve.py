"""Resolve Tier-0 project awareness for the basecamp MCP context server.

Mirrors the project-detection logic of the (retired) Pi extension's
``pi/core/project/config.ts`` so the Claude Code plugin resolves the
``projects`` section of ``~/.pi/basecamp/config.json`` identically. Detection
is by git-repo-root **path equality** (not org/name identity): the session's
git top-level is compared against each project's resolved ``repo_root``.

Path resolution matches ``config.ts`` exactly — including that ``repo_root`` is
normalised with :func:`os.path.abspath` (like TS ``path.resolve``), which does
*not* follow symlinks. The config schema owner is imported rather than
re-modelled, so this module cannot drift from the writer.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.core.projects import ProjectConfig, load_projects
from basecamp.core.settings import Settings

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class ProjectAwareness:
    """Resolved awareness for the session's working directory."""

    project_name: str | None = None
    repo_root: str | None = None
    related_dirs: list[str] = field(default_factory=list)
    context_text: str | None = None
    ambiguous: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def projected(self) -> bool:
        """Whether the cwd resolved to exactly one configured project."""
        return self.project_name is not None


def resolve_config_dir(directory: str, home: Path) -> str:
    """Resolve a config-relative directory the way ``config.ts`` does.

    ``~`` -> home; ``~/x`` -> home/x; absolute -> unchanged; relative ->
    joined onto home (never cwd).
    """
    if directory == "~":
        return str(home)
    if directory.startswith("~/"):
        return str(home / directory[2:])
    if os.path.isabs(directory):
        return directory
    return str(home / directory)


def _context_dir(home: Path) -> Path:
    # Mirrors basecamp.core.paths.USER_CONTEXT_DIR (~/.pi/basecamp/context),
    # parameterised on home so the resolver stays testable.
    return home / ".pi" / "basecamp" / "context"


def _git_toplevel(cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    toplevel = result.stdout.strip()
    return toplevel or None


def _existing_dirs(dirs: list[str], home: Path) -> list[str]:
    resolved: list[str] = []
    for entry in dirs:
        if not isinstance(entry, str) or not entry:
            continue
        candidate = resolve_config_dir(entry, home)
        if os.path.isdir(candidate):
            resolved.append(candidate)
    return resolved


def _load_context(name: str, home: Path) -> str | None:
    try:
        return (_context_dir(home) / f"{name}.md").read_text()
    except OSError:
        return None


def _match_projects(projects: dict[str, ProjectConfig], target: str, home: Path) -> list[tuple[str, ProjectConfig]]:
    matches: list[tuple[str, ProjectConfig]] = []
    for name, project in projects.items():
        if not project.repo_root.strip():
            continue
        if os.path.abspath(resolve_config_dir(project.repo_root, home)) == target:
            matches.append((name, project))
    return matches


def resolve_awareness(repo_root: str | None, *, home: Path, config: Settings | None = None) -> ProjectAwareness:
    """Resolve awareness from an already-known git repo root (pure; no git call)."""
    if repo_root is None:
        return ProjectAwareness()

    target = os.path.abspath(repo_root)
    try:
        projects = load_projects(config)
    except LauncherError as exc:
        return ProjectAwareness(repo_root=target, warnings=[f"Could not read basecamp projects: {exc}"])

    matches = _match_projects(projects, target, home)

    if len(matches) > 1:
        names = ", ".join(sorted(name for name, _ in matches))
        warning = (
            f"Project detection ambiguous: {target} is configured for {names}; treating the session as unprojected."
        )
        return ProjectAwareness(repo_root=target, ambiguous=True, warnings=[warning])

    if not matches:
        return ProjectAwareness(repo_root=target)

    name, project = matches[0]
    context_text = _load_context(project.context, home) if project.context else None
    return ProjectAwareness(
        project_name=name,
        repo_root=target,
        related_dirs=_existing_dirs(project.additional_dirs, home),
        context_text=context_text,
    )


def resolve_project(cwd: str, *, home: Path | None = None, config: Settings | None = None) -> ProjectAwareness:
    """Resolve awareness for a working directory (runs ``git rev-parse``)."""
    resolved_home = home or Path.home()
    return resolve_awareness(_git_toplevel(cwd), home=resolved_home, config=config)
