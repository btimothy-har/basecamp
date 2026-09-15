"""Project-aware launcher for the Basecamp OMP extension."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.core.models import ProjectConfig
from basecamp.core.projects import load_projects
from basecamp.core.settings import settings

_GIT_TIMEOUT_SECONDS = 5

# Bomp must select roots before OMP starts. These pinned 18.1.21 built-ins
# consume any following token, even a flag-looking one such as ``--cwd``.
_OMP_STRING_VALUE_FLAGS = frozenset(
    {
        "--add-dir",
        "--alias",
        "--append-system-prompt",
        "--api-key",
        "--approval-mode",
        "--config",
        "--cwd",
        "--export",
        "--extension",
        "--fork",
        "--hook",
        "--max-time",
        "--mode",
        "--model",
        "--models",
        "--plan",
        "--plan-yolo-into",
        "--plugin-dir",
        "--prewalk-into",
        "--profile",
        "--prompt-cache-key",
        "--provider",
        "--provider-session-id",
        "--service-tier",
        "--session-dir",
        "--skills",
        "--slow",
        "--smol",
        "--system-prompt",
        "--thinking",
        "--tools",
        "--trusted-extension",
        "-e",
    }
)


@dataclass(frozen=True)
class LaunchPlan:
    """Arguments and diagnostics for one OMP launch."""

    argv: list[str]
    project_name: str | None
    warnings: tuple[str, ...]


def effective_cwd(
    cwd: Path,
    args: Sequence[str],
    *,
    home: Path | None = None,
) -> Path:
    """Resolve the directory OMP will use without consuming its arguments."""
    selected = cwd
    has_explicit_cwd = False
    allows_home = False
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--":
            break
        if argument == "--cwd" and index + 1 < len(args):
            value = args[index + 1]
            selected = _resolve_cli_path(value, cwd)
            has_explicit_cwd = bool(value)
            index += 2
            continue
        if argument.startswith("--cwd="):
            value = argument.removeprefix("--cwd=")
            selected = _resolve_cli_path(value, cwd)
            has_explicit_cwd = bool(value)
            index += 1
            continue
        if argument == "--allow-home" or argument.startswith("--allow-home="):
            allows_home = True
            index += 1
            continue
        if argument in _OMP_STRING_VALUE_FLAGS and index + 1 < len(args):
            index += 2
            continue
        index += 1
    return _apply_omp_home_fallback(
        selected.resolve(),
        home=(home or Path.home()).resolve(),
        has_explicit_cwd=has_explicit_cwd,
        allows_home=allows_home,
    )


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


def _resolve_cli_path(value: str, cwd: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else cwd / path


def _apply_omp_home_fallback(
    selected: Path,
    *,
    home: Path,
    has_explicit_cwd: bool,
    allows_home: bool,
) -> Path:
    if has_explicit_cwd or allows_home or selected != home:
        return selected
    for candidate in (home / "tmp", Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())):
        try:
            if candidate.is_dir() and candidate.resolve() != selected:
                return candidate.resolve()
        except OSError:
            continue
    return selected


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
) -> None:
    """Validate and replace this process with the project-aware OMP launch."""
    if shutil.which("omp") is None:
        message = "OMP executable not found on PATH; install Oh My Pi before using bomp."
        raise LauncherError(message)

    package = extension_dir or resolve_extension_dir(install_dir=settings.install_dir)
    if not _is_omp_package(package):
        message = f"Basecamp OMP extension not found at {package}; run basecamp install."
        raise LauncherError(message)

    configured_projects = projects if projects is not None else load_projects()
    plan = build_launch(cwd or Path.cwd(), args, configured_projects, package)
    for warning in plan.warnings:
        print(f"bomp: warning: {warning}", file=sys.stderr)

    try:
        os.execvp("omp", plan.argv)
    except OSError as exc:
        message = f"Could not start OMP: {exc}"
        raise LauncherError(message) from exc


def main() -> None:
    """Console entry point for ``bomp``."""
    try:
        run_launch(sys.argv[1:])
    except LauncherError as exc:
        print(f"bomp: error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
