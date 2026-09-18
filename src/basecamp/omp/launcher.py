"""Project-aware launcher for the Basecamp OMP extension."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

from basecamp.core.exceptions import LauncherError
from basecamp.core.models import ProjectConfig
from basecamp.core.projects import load_projects
from basecamp.core.settings import settings
from basecamp.omp.arguments import effective_cwd
from basecamp.omp.detached_plan import plan_detached_launch
from basecamp.omp.detached_run import (
    DetachedWorkspace,
    cleanup_failed_creation,
    create_workspace,
    defer_termination_signals,
    remove_workspace,
    report_cleanup_failure,
    reserve_workspace_path,
    supervise_omp,
)
from basecamp.omp.launch_arguments import (
    inspect_launch_arguments,
    resolve_relocated_path_arguments,
    resolve_session_dir_argument,
    resolve_session_dir_environment,
)
from basecamp.omp.launch_plan import (
    build_launch,
    canonical_checkout,
    is_omp_package,
    resolve_extension_dir,
    run_git,
)
from basecamp.omp.scratch_cleanup import cleanup_automatic_workspace
from basecamp.omp.snapshot import capture_snapshot, delete_snapshot_ref, matches_snapshot, restore_snapshot
from basecamp.omp.workspace_environment import (
    clear_git_location_environment,
    require_safe_snapshot_paths,
    require_safe_workspace_path,
)


def run_launch(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    projects: Mapping[str, ProjectConfig] | None = None,
    extension_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int | None:
    """Start OMP directly or supervise a fresh canonical scratch."""
    omp_executable = shutil.which("omp")
    if omp_executable is None:
        message = "OMP executable not found on PATH; install Oh My Pi before using bomp."
        raise LauncherError(message)

    package = extension_dir or resolve_extension_dir(install_dir=settings.install_dir)
    if not is_omp_package(package):
        message = f"Basecamp OMP extension not found at {package}; run basecamp install."
        raise LauncherError(message)

    active_cwd = cwd or Path.cwd()
    configured_projects = projects if projects is not None else load_projects()
    child_environment = dict(os.environ if environ is None else environ)
    arguments = inspect_launch_arguments(args)
    if arguments.disposition == "discard":
        return _run_detached_launch(
            arguments.omp_args,
            cwd=active_cwd,
            projects=configured_projects,
            package=package,
            omp_executable=omp_executable,
            environ=child_environment,
            implicit=False,
        )
    if arguments.disposition == "auto" and _uses_automatic_scratch(
        active_cwd,
        arguments.omp_args,
    ):
        source_cwd = effective_cwd(active_cwd, arguments.omp_args)
        auto_resume = _native_auto_resume_state(
            omp_executable,
            cwd=source_cwd,
            profile=arguments.profile,
            environ=child_environment,
        )
        if auto_resume is False:
            return _run_detached_launch(
                arguments.omp_args,
                cwd=active_cwd,
                projects=configured_projects,
                package=package,
                omp_executable=omp_executable,
                environ=child_environment,
                implicit=True,
            )

    plan = build_launch(active_cwd, arguments.omp_args, configured_projects, package)
    _print_warnings(plan.warnings)
    try:
        os.execvpe("omp", plan.argv, child_environment)
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
    implicit: bool,
) -> int:
    if implicit:
        return _run_automatic_launch(
            args,
            cwd=cwd,
            projects=projects,
            package=package,
            omp_executable=omp_executable,
            environ=environ,
        )
    return _run_discard_launch(
        args,
        cwd=cwd,
        projects=projects,
        package=package,
        omp_executable=omp_executable,
        environ=environ,
    )


def _run_discard_launch(
    args: Sequence[str],
    *,
    cwd: Path,
    projects: Mapping[str, ProjectConfig],
    package: Path,
    omp_executable: str,
    environ: Mapping[str, str],
) -> int:
    """Explicit --detached: force-discard semantics with no persistent records."""
    managed_environment = clear_git_location_environment(environ)
    detached = plan_detached_launch(
        cwd,
        args,
        omp_executable=omp_executable,
        environ=managed_environment,
        allow_dirty=False,
    )
    status: int | None = None
    with defer_termination_signals() as termination:
        workspace = create_workspace(detached, omp_executable=omp_executable, environ=managed_environment)
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
                status = supervise_omp(launch.argv, cwd=workspace.launch_cwd, environ=managed_environment)
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


def _run_automatic_launch(
    args: Sequence[str],
    *,
    cwd: Path,
    projects: Mapping[str, ProjectConfig],
    package: Path,
    omp_executable: str,
    environ: Mapping[str, str],
) -> int:
    """Supervise a canonical scratch containing a coherent copy of source WIP."""
    source_cwd = effective_cwd(cwd, args)
    managed_args, argument_session_dir = resolve_session_dir_argument(args, source_cwd)
    managed_args = resolve_relocated_path_arguments(managed_args, source_cwd)
    managed_environment, environment_session_dir = resolve_session_dir_environment(
        dict(environ),
        source_cwd,
    )
    managed_environment = clear_git_location_environment(managed_environment)
    detached = plan_detached_launch(
        cwd,
        managed_args,
        omp_executable=omp_executable,
        environ=managed_environment,
        allow_dirty=True,
    )
    session_dir_value = argument_session_dir or environment_session_dir
    session_dir = Path(session_dir_value) if session_dir_value is not None else None
    workspace_id = secrets.token_hex(16)
    status: int | None = None
    with tempfile.TemporaryDirectory(prefix=f"bomp-{workspace_id}-snapshot-") as raw_snapshot_dir:
        snapshot_dir = Path(raw_snapshot_dir) / "state"
        require_safe_snapshot_paths(
            snapshot_dir=snapshot_dir,
            session_dir=session_dir,
            canonical_root=detached.source.root,
            worktree_base=detached.worktree_base,
        )
        snapshot = None
        workspace_path: Path | None = None
        workspace: DetachedWorkspace | None = None
        with defer_termination_signals() as termination:
            try:
                snapshot = capture_snapshot(
                    detached.source.root,
                    snapshot_dir,
                    workspace_id,
                )
                detached = replace(detached, source=replace(detached.source, head=snapshot.head))
                workspace_path = reserve_workspace_path(detached, workspace_id)
                require_safe_workspace_path(
                    workspace_path=workspace_path,
                    snapshot_dir=snapshot_dir,
                    session_dir=session_dir,
                    canonical_root=detached.source.root,
                )
                if termination.status is None:
                    workspace = create_workspace(
                        detached,
                        omp_executable=omp_executable,
                        environ=managed_environment,
                        workspace_path=workspace_path,
                    )
                    restore_snapshot(snapshot, workspace.path)
                    if not matches_snapshot(snapshot, workspace.path):
                        message = (
                            f"Scratch workspace {workspace.path} does not match the captured snapshot; "
                            "the original checkout is unchanged."
                        )
                        raise LauncherError(message)
                if termination.status is None and workspace is not None:
                    if snapshot.has_uncommitted_work:
                        print(
                            "bomp: Uncommitted work copied into scratch; your original checkout is unchanged.",
                            file=sys.stderr,
                        )
                    print(
                        f"bomp: temporary worktree {workspace.path}; use /wt <branch> to retain execution work.",
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
                    status = supervise_omp(
                        launch.argv,
                        cwd=workspace.launch_cwd,
                        environ=managed_environment,
                    )
            finally:
                retained_reason = None
                if workspace is not None and snapshot is not None:
                    cleanup = cleanup_automatic_workspace(detached.source.root, workspace.path, snapshot)
                    failure = cleanup.failure
                    retained_reason = cleanup.retained_reason
                elif workspace_path is not None:
                    failure = cleanup_failed_creation(detached.source.root, workspace_path)
                else:
                    failure = None
                if retained_reason is not None and workspace_path is not None:
                    print(f"bomp: retaining temporary worktree {workspace_path}: {retained_reason}.", file=sys.stderr)
                if failure is not None and workspace_path is not None:
                    report_cleanup_failure(failure, workspace_path=workspace_path, stream=sys.stderr)
                if snapshot is not None:
                    release_error = delete_snapshot_ref(snapshot, detached.source.root)
                    if release_error is not None:
                        print(f"bomp: warning: could not release scratch snapshot: {release_error}", file=sys.stderr)
            if termination.status is not None:
                return termination.status
    if status is None:
        message = "Detached OMP launch ended without a child status."
        raise LauncherError(message)
    return status


def _uses_automatic_scratch(cwd: Path, args: Sequence[str]) -> bool:
    try:
        if not sys.stdin.isatty():
            return False
    except OSError:
        return False
    source_cwd = effective_cwd(cwd, args)
    root_text = run_git(source_cwd, "rev-parse", "--show-toplevel")
    if root_text is None:
        return False
    canonical = canonical_checkout(source_cwd)
    return canonical is not None and Path(root_text).resolve() == canonical.resolve()


def _native_auto_resume_state(
    omp_executable: str,
    *,
    cwd: Path,
    profile: str | None,
    environ: Mapping[str, str],
) -> bool | None:
    """Read OMP's authoritative startup-resume setting without parsing its config."""
    arguments = [omp_executable]
    if profile is not None:
        arguments.extend(("--profile", profile))
    arguments.extend(("config", "get", "autoResume", "--json"))
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            env=dict(environ),
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout).get("value")
    except (AttributeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, bool) else None


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
