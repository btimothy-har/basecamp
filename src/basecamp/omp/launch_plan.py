"""OMP launch-plan construction from Basecamp project configuration."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.models import ProjectConfig
from basecamp.omp.arguments import effective_cwd

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class LaunchPlan:
    """Arguments and diagnostics for one OMP launch."""

    argv: list[str]
    project_name: str | None
    warnings: tuple[str, ...]


def canonical_checkout(cwd: Path) -> Path | None:
    """Return the primary checkout for the Git repository containing ``cwd``."""
    output = run_git(cwd, "worktree", "list", "--porcelain")
    if output is None:
        return None
    for line in output.splitlines():
        if line.startswith("worktree "):
            return Path(line.removeprefix("worktree ")).resolve()
    return None


def resolve_extension_dir(
    *,
    install_dir: str | None,
    module_file: Path | None = None,
) -> Path:
    """Locate root ``omp/`` from an editable checkout or install metadata."""
    source_root = (module_file or Path(__file__)).resolve().parents[3]
    source_package = source_root / "omp"
    if is_omp_package(source_package):
        return source_package
    if install_dir:
        return Path(install_dir).expanduser().resolve() / "omp"
    return source_package


def build_launch(
    cwd: Path,
    args: Sequence[str],
    projects: Mapping[str, ProjectConfig],
    extension_dir: Path,
    *,
    home: Path | None = None,
) -> LaunchPlan:
    """Build OMP argv from the configured project containing the effective cwd."""
    active_home = (home or Path.home()).resolve()
    checkout = canonical_checkout(effective_cwd(cwd, args, home=active_home))
    project_name, roots, warnings = _project_roots(checkout, projects, active_home)
    generated = ["--extension", str(extension_dir.resolve())]
    generated.extend(f"--add-dir={root}" for root in roots)
    return LaunchPlan(
        argv=["omp", *generated, *args],
        project_name=project_name,
        warnings=tuple(warnings),
    )


def _project_roots(
    checkout: Path | None,
    projects: Mapping[str, ProjectConfig],
    home: Path,
) -> tuple[str | None, list[Path], list[str]]:
    if checkout is None:
        return None, [], []

    matches: list[tuple[str, ProjectConfig]] = []
    for name, project in projects.items():
        try:
            if _configured_path(project.repo_root, home) == checkout:
                matches.append((name, project))
        except (OSError, RuntimeError):
            continue
    if not matches:
        return None, [], []
    if len(matches) > 1:
        names = ", ".join(sorted(name for name, _project in matches))
        warning = (
            f"Multiple Basecamp projects match {checkout}: {names}; starting without inferred project directories."
        )
        return None, [], [warning]

    name, project = matches[0]
    roots: list[Path] = []
    warnings: list[str] = []
    for configured in project.additional_dirs:
        try:
            root = _configured_path(configured, home)
            is_available = root.is_dir() and os.access(root, os.R_OK | os.X_OK)
        except (OSError, RuntimeError):
            root = _absolute_configured_path(configured, home)
            is_available = False
        if is_available:
            roots.append(root)
        else:
            warnings.append(f"Skipping unavailable Basecamp project directory: {root}")
    return name, roots, warnings


def _configured_path(value: str, home: Path) -> Path:
    return _absolute_configured_path(value, home).resolve()


def _absolute_configured_path(value: str, home: Path) -> Path:
    if value == "~":
        return home
    if value.startswith("~/"):
        return home / value[2:]
    path = Path(value)
    return path if path.is_absolute() else home / path


def is_omp_package(path: Path) -> bool:
    return (path / "package.json").is_file() and (path / "extension.ts").is_file()


def run_git(cwd: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
