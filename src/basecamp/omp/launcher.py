"""Project-aware launcher for the Basecamp OMP extension."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.core.models import ProjectConfig
from basecamp.core.projects import load_projects
from basecamp.core.settings import settings
from basecamp.omp.arguments import effective_cwd
from basecamp.omp.detached_plan import is_detached_requested, plan_detached_launch
from basecamp.omp.detached_run import (
    create_workspace,
    defer_termination_signals,
    remove_workspace,
    report_cleanup_failure,
    supervise_omp,
)

_GIT_TIMEOUT_SECONDS = 5


@dataclass(frozen=True)
class LaunchPlan:
    """Arguments and diagnostics for one OMP launch."""

    argv: list[str]
    project_name: str | None
    warnings: tuple[str, ...]


def canonical_checkout(cwd: Path) -> Path | None:
    """Return the primary checkout for the Git repository containing ``cwd``."""
    output = _run_git(cwd, "worktree", "list", "--porcelain")
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
    if _is_omp_package(source_package):
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


def _is_omp_package(path: Path) -> bool:
    return (path / "package.json").is_file() and (path / "extension.ts").is_file()


def _run_git(cwd: Path, *args: str) -> str | None:
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


def run_launch(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    projects: Mapping[str, ProjectConfig] | None = None,
    extension_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int | None:
    """Start OMP directly or supervise one disposable detached launch."""
    omp_executable = shutil.which("omp")
    if omp_executable is None:
        message = "OMP executable not found on PATH; install Oh My Pi before using bomp."
        raise LauncherError(message)

    package = extension_dir or resolve_extension_dir(install_dir=settings.install_dir)
    if not _is_omp_package(package):
        message = f"Basecamp OMP extension not found at {package}; run basecamp install."
        raise LauncherError(message)

    active_cwd = cwd or Path.cwd()
    configured_projects = projects if projects is not None else load_projects()
    if is_detached_requested(args):
        return _run_detached_launch(
            args,
            cwd=active_cwd,
            projects=configured_projects,
            package=package,
            omp_executable=omp_executable,
            environ=os.environ if environ is None else environ,
        )

    plan = build_launch(active_cwd, args, configured_projects, package)
    _print_warnings(plan.warnings)
    try:
        os.execvp("omp", plan.argv)
    except OSError as exc:
        message = f"Could not start OMP: {exc}"
        raise LauncherError(message) from exc
    return None


def _run_detached_launch(
    args: Sequence[str],
    *,
    cwd: Path,
    projects: Mapping[str, ProjectConfig],
    package: Path,
    omp_executable: str,
    environ: Mapping[str, str],
) -> int:
    detached = plan_detached_launch(
        cwd,
        args,
        omp_executable=omp_executable,
        environ=environ,
    )
    status: int | None = None
    with defer_termination_signals() as termination:
        workspace = create_workspace(detached, omp_executable=omp_executable, environ=environ)
        try:
            if termination.status is None:
                print(
                    f"bomp: detached worktree {workspace.path}; use /wt <branch> before exit to retain code.",
                    file=sys.stderr,
                )
                _print_warnings(workspace.warnings)
                launch = build_launch(
                    workspace.launch_cwd,
                    detached.arguments.omp_args,
                    projects,
                    package,
                )
                _print_warnings(launch.warnings)
            if termination.status is None:
                status = supervise_omp(launch.argv, cwd=workspace.launch_cwd, environ=environ)
        finally:
            failure = remove_workspace(detached.source.root, workspace.path)
            if failure is not None:
                report_cleanup_failure(failure, workspace_path=workspace.path, stream=sys.stderr)
    if termination.status is not None:
        return termination.status
    if status is None:
        message = "Detached OMP launch ended without a child status."
        raise LauncherError(message)
    return status


def _print_warnings(warnings: Sequence[str]) -> None:
    for warning in warnings:
        print(f"bomp: warning: {warning}", file=sys.stderr)


def main() -> None:
    """Console entry point for ``bomp``."""
    try:
        status = run_launch(sys.argv[1:])
    except LauncherError as exc:
        print(f"bomp: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if status is not None:
        raise SystemExit(status)
