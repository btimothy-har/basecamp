"""Argument and repository planning for disposable OMP launches."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.omp.launch_arguments import DetachedArguments, parse_detached_arguments

_COMMAND_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class GitSource:
    """Clean source checkout used to create a detached worktree."""

    root: Path
    relative_cwd: Path
    head: str


@dataclass(frozen=True)
class DetachedPlan:
    """Inputs required before the disposable worktree is created."""

    arguments: DetachedArguments
    source: GitSource
    worktree_base: Path


def plan_detached_launch(
    cwd: Path,
    args: Sequence[str],
    *,
    omp_executable: str,
    environ: Mapping[str, str],
    home: Path | None = None,
    allow_dirty: bool = False,
) -> DetachedPlan:
    """Resolve and validate all detached-launch inputs without creating state."""
    active_home = (home or Path.home()).resolve()
    arguments = parse_detached_arguments(cwd, args, home=active_home)
    source = resolve_git_source(arguments.source_cwd, allow_dirty=allow_dirty)
    worktree_base = resolve_worktree_base(
        omp_executable,
        source_cwd=arguments.source_cwd,
        profile=arguments.profile,
        environ=environ,
        home=active_home,
    )
    if worktree_base == source.root or worktree_base.is_relative_to(source.root):
        message = f"Detached mode requires OMP's worktree base to be outside the source checkout: {worktree_base}"
        raise LauncherError(message)
    return DetachedPlan(arguments=arguments, source=source, worktree_base=worktree_base)


def resolve_git_source(cwd: Path, *, allow_dirty: bool = False) -> GitSource:
    """Resolve a Git worktree and its selected nested directory."""
    selected = cwd.resolve()
    if not selected.is_dir():
        message = f"Detached mode requires an existing directory: {selected}"
        raise LauncherError(message)
    root_text = _run_git(selected, "rev-parse", "--show-toplevel")
    root = Path(root_text).resolve()
    try:
        relative_cwd = selected.relative_to(root)
    except ValueError as exc:
        message = f"Could not map {selected} inside its Git checkout {root}."
        raise LauncherError(message) from exc
    if not allow_dirty:
        status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if status:
            message = f"Detached mode requires a clean source checkout: {root}"
            raise LauncherError(message)
    head = _run_git(root, "rev-parse", "--verify", "HEAD")
    return GitSource(root=root, relative_cwd=relative_cwd, head=head)


def resolve_worktree_base(
    omp_executable: str,
    *,
    source_cwd: Path,
    profile: str | None,
    environ: Mapping[str, str],
    home: Path,
) -> Path:
    """Resolve OMP's effective managed-worktree base directory."""
    env_base = _absolute_omp_path(environ.get("OMP_WORKTREE_DIR"), home)
    if env_base is not None:
        return env_base

    command = [omp_executable]
    if profile is not None:
        command.extend(("--profile", profile))
    command.extend(("config", "get", "worktree.base", "--json"))
    try:
        result = subprocess.run(
            command,
            cwd=source_cwd,
            env=dict(environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Could not resolve OMP worktree settings: {exc}"
        raise LauncherError(message) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        message = f"Could not resolve OMP worktree settings: {detail}"
        raise LauncherError(message)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        message = "OMP returned invalid JSON for worktree.base."
        raise LauncherError(message) from exc
    configured = payload.get("value") if isinstance(payload, dict) else None
    config_base = _absolute_omp_path(configured if isinstance(configured, str) else None, home)
    return config_base or _default_worktree_base(profile, environ, home, source_cwd)


def _run_git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        message = f"Could not inspect Git checkout at {cwd}: {exc}"
        raise LauncherError(message) from exc
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        message = f"Could not inspect Git checkout at {cwd}: {detail}"
        raise LauncherError(message)
    return result.stdout.strip()


def _absolute_omp_path(value: str | None, home: Path) -> Path | None:
    trimmed = value.strip() if value is not None else ""
    if not trimmed:
        return None
    if trimmed == "~":
        return home
    if trimmed.startswith(("~/", "~\\")):
        return Path(f"{home}{trimmed[1:]}").resolve()
    path = Path(trimmed)
    return path.resolve() if path.is_absolute() else None


def _default_worktree_base(
    profile: str | None,
    environ: Mapping[str, str],
    home: Path,
    source_cwd: Path,
) -> Path:
    active_profile = _active_profile(profile, environ)
    config_name = (environ.get("PI_CONFIG_DIR") or ".omp").lstrip("/\\")
    base_config_root = (home / config_name).resolve()
    config_root = base_config_root
    if active_profile is not None:
        config_root = config_root / "profiles" / active_profile

    xdg_data = environ.get("XDG_DATA_HOME")
    has_custom_agent_dir = _has_custom_agent_dir(
        active_profile,
        environ,
        source_cwd=source_cwd,
        base_config_root=base_config_root,
    )
    if sys.platform in {"darwin", "linux"} and xdg_data and not has_custom_agent_dir:
        xdg_root = Path(xdg_data) / "omp"
        if active_profile is not None:
            xdg_root = xdg_root / "profiles" / active_profile
        if xdg_root.is_absolute() and xdg_root.exists():
            return (xdg_root / "wt").resolve()
    return (config_root / "wt").resolve()


def _has_custom_agent_dir(
    active_profile: str | None,
    environ: Mapping[str, str],
    *,
    source_cwd: Path,
    base_config_root: Path,
) -> bool:
    value = environ.get("PI_CODING_AGENT_DIR")
    if active_profile is not None or not value:
        return False
    configured = Path(value)
    resolved = (source_cwd / configured).resolve() if not configured.is_absolute() else configured.resolve()
    default_agent = (base_config_root / "agent").resolve()
    if resolved == default_agent:
        return False

    bypassed_profile = _normalized_profile(environ.get("PI_PROFILE"))
    if "OMP_PROFILE" in environ and bypassed_profile is not None:
        profile_agent = (base_config_root / "profiles" / bypassed_profile / "agent").resolve()
        if resolved == profile_agent:
            return False
    return True


def _active_profile(profile: str | None, environ: Mapping[str, str]) -> str | None:
    selected = profile
    if selected is None:
        selected = environ.get("OMP_PROFILE") if "OMP_PROFILE" in environ else environ.get("PI_PROFILE")
    return _normalized_profile(selected)


def _normalized_profile(profile: str | None) -> str | None:
    normalized = profile.strip() if profile is not None else ""
    return None if not normalized or normalized == "default" else normalized
