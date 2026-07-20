"""Known-retired local-state detection and archive-only cleanup."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from .archive import DoctorArchive, raise_walk_error
from .models import DoctorCheck, DoctorPaths, DoctorReport, RepairAction, RepairKind, Severity
from .process import DaemonState, inspect_daemon

_ACTIVE_TOP_LEVEL = frozenset(
    {
        "backups",
        "browser",
        "companion",
        "config.json",
        "config.lock",
        "context",
        "core",
        "prompts",
        "styles",
        "swarm",
        "tasks",
    }
)
_RETIRED_TOP_LEVEL = frozenset({"claude", "workspace", "workstream-launches"})
_WORKSPACE_KNOWN = frozenset({"context", "model-aliases.json", "projects.json", "prompts", "styles"})


@dataclass(frozen=True)
class RetiredArtifact:
    code: str
    label: str
    path: Path
    daemon_guarded: bool = False


def inspect_retired_artifacts(paths: DoctorPaths) -> DoctorReport:
    """Report archive-only artifacts, excluded paths, and unknown local state."""
    report = DoctorReport()
    for artifact in _archive_only(paths):
        _inspect_artifact(artifact, report)
    _inspect_workspace(paths, report)
    _report_excluded(paths, report)
    _report_unknown(paths, report)
    return report


def repair_retired_artifacts(paths: DoctorPaths, archive: DoctorArchive) -> list[DoctorCheck]:
    """Archive each independently-safe retired artifact; never import its data."""
    errors: list[DoctorCheck] = []
    for artifact in _archive_only(paths):
        error = _artifact_error(artifact)
        if error is None and artifact.daemon_guarded:
            error = _retired_daemon_error(artifact.path)
        if error is None:
            error = _artifact_content_error(artifact)
        if error is not None:
            continue
        try:
            archive.retire(artifact.path, artifact.path.relative_to(paths.root))
        except OSError as exc:
            errors.append(_repair_error(artifact, exc))

    workspace_error = _workspace_error(paths.workspace)
    if workspace_error is None and paths.workspace.exists():
        artifact = RetiredArtifact("workspace", "legacy workspace wrapper", paths.workspace)
        try:
            if not _is_empty_directory(paths.workspace):
                return errors
            archived_workspace = archive.path / "retired" / "workspace" if archive.path is not None else None
            if archived_workspace is not None and archived_workspace.is_dir():
                paths.workspace.rmdir()
            else:
                archive.retire(paths.workspace, Path("workspace"))
        except OSError as exc:
            errors.append(_repair_error(artifact, exc))
    return errors


def _archive_only(paths: DoctorPaths) -> tuple[RetiredArtifact, ...]:
    return (
        RetiredArtifact("workstream_launches", "retired workstream launch index", paths.workstream_launches),
        RetiredArtifact("companion_analysis", "dead companion analysis sidecars", paths.companion_analysis),
        RetiredArtifact("claude_runtime", "reverted Claude runtime", paths.claude_runtime, daemon_guarded=True),
    )


def _inspect_artifact(artifact: RetiredArtifact, report: DoctorReport) -> None:
    error = _artifact_error(artifact)
    if error is not None:
        if artifact.path.exists() or artifact.path.is_symlink():
            report.add_check(DoctorCheck("retired", artifact.code, Severity.ERROR, error, artifact.path))
        return
    if artifact.daemon_guarded:
        daemon_error = _retired_daemon_error(artifact.path)
        if daemon_error is not None:
            report.add_check(
                DoctorCheck("retired", f"{artifact.code}_live", Severity.ERROR, daemon_error, artifact.path)
            )
            return
    content_error = _artifact_content_error(artifact)
    if content_error is not None:
        report.add_check(DoctorCheck("retired", artifact.code, Severity.ERROR, content_error, artifact.path))
        return
    report.add_check(
        DoctorCheck(
            "retired",
            artifact.code,
            Severity.REPAIRABLE,
            f"The {artifact.label} can be archived without importing it.",
            artifact.path,
        )
    )
    report.add_action(
        RepairAction(
            code=f"retired.archive_{artifact.code}",
            kind=RepairKind.ARCHIVE,
            description=f"Archive the {artifact.label}.",
            paths=(artifact.path,),
        )
    )


def _artifact_error(artifact: RetiredArtifact) -> str | None:
    try:
        mode = artifact.path.lstat().st_mode
    except FileNotFoundError:
        return f"The {artifact.label} is absent."
    except OSError as exc:
        return f"Could not inspect the {artifact.label}: {exc}"
    if stat.S_ISLNK(mode):
        return f"The {artifact.label} is a symlink; archival is disabled."
    if not stat.S_ISDIR(mode):
        return f"The {artifact.label} is not a directory; archival is disabled."
    return None


def _artifact_content_error(artifact: RetiredArtifact) -> str | None:
    try:
        special = _first_unsupported_path(artifact.path)
    except OSError as exc:
        return f"Could not fully inspect the {artifact.label}: {exc}"
    if special is not None:
        return f"The {artifact.label} contains a symlink or special file: {special}"
    return None


def _retired_daemon_error(runtime: Path) -> str | None:
    status = inspect_daemon(runtime / "daemon.sock", runtime / "daemon.pid", runtime / "daemon.spawn.lock")
    if status.state is DaemonState.DOWN:
        return None
    if status.state is DaemonState.LIVE:
        return "The retired Claude daemon is still running; its runtime was retained."
    return "Retired Claude daemon liveness is ambiguous; its runtime was retained."


def _inspect_workspace(paths: DoctorPaths, report: DoctorReport) -> None:
    error = _workspace_error(paths.workspace)
    if error is not None:
        if paths.workspace.exists() or paths.workspace.is_symlink():
            report.add_check(DoctorCheck("retired", "workspace", Severity.ERROR, error, paths.workspace))
        return
    if not paths.workspace.exists():
        return
    try:
        children = {path.name for path in paths.workspace.iterdir()}
    except OSError as exc:
        report.add_check(
            DoctorCheck(
                "retired",
                "workspace_unreadable",
                Severity.ERROR,
                f"Could not inspect legacy workspace contents: {exc}",
                paths.workspace,
            )
        )
        return
    unknown = sorted(children - _WORKSPACE_KNOWN)
    if unknown:
        report.add_check(
            DoctorCheck(
                "retired",
                "workspace_unknown",
                Severity.WARNING,
                "Legacy workspace contains unrecognized entries and was retained.",
                paths.workspace,
            )
        )
    elif not children:
        report.add_check(
            DoctorCheck(
                "retired",
                "workspace",
                Severity.REPAIRABLE,
                "Empty legacy workspace wrapper can be archived.",
                paths.workspace,
            )
        )
        report.add_action(
            RepairAction(
                code="retired.archive_workspace",
                kind=RepairKind.ARCHIVE,
                description="Archive the empty legacy workspace wrapper.",
                paths=(paths.workspace,),
            )
        )


def _workspace_error(path: Path) -> str | None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"Could not inspect legacy workspace: {exc}"
    if stat.S_ISLNK(mode):
        return "Legacy workspace is a symlink; archival is disabled."
    if not stat.S_ISDIR(mode):
        return "Legacy workspace is not a directory; archival is disabled."
    return None


def _report_excluded(paths: DoctorPaths, report: DoctorReport) -> None:
    if paths.browser_profile.exists() or paths.browser_profile.is_symlink():
        report.add_check(
            DoctorCheck(
                "excluded",
                "browser_profile",
                Severity.INFO,
                "Legacy browser profile is explicitly excluded and was not changed.",
                paths.browser_profile,
            )
        )


def _report_unknown(paths: DoctorPaths, report: DoctorReport) -> None:
    known = _ACTIVE_TOP_LEVEL | _RETIRED_TOP_LEVEL
    try:
        top_level = sorted(
            (path for path in paths.root.iterdir() if path.name not in known),
            key=lambda path: path.name,
        )
    except OSError as exc:
        report.add_check(
            DoctorCheck("layout", "unknown_scan", Severity.WARNING, f"Could not inspect unknown local state: {exc}")
        )
        return
    for index, path in enumerate(top_level, start=1):
        report.add_check(
            DoctorCheck(
                "unknown",
                f"top_level_{index}",
                Severity.INFO,
                "Unrecognized local-state entry was retained.",
                path,
            )
        )
    _report_nested_unknowns(paths.root / "companion", {"analysis", "snapshots"}, "companion", report)
    _report_nested_unknowns(paths.root / "browser", {"playwright-output", "profile"}, "browser", report)


def _report_nested_unknowns(root: Path, known: set[str], code: str, report: DoctorReport) -> None:
    if not root.is_dir() or root.is_symlink():
        return
    try:
        unknown = sorted((path for path in root.iterdir() if path.name not in known), key=lambda path: path.name)
    except OSError as exc:
        report.add_check(
            DoctorCheck(
                "unknown",
                f"{code}_scan",
                Severity.WARNING,
                f"Could not inspect unknown {code} state: {exc}",
                root,
            )
        )
        return
    for index, path in enumerate(unknown, start=1):
        report.add_check(
            DoctorCheck(
                "unknown",
                f"{code}_{index}",
                Severity.INFO,
                f"Unrecognized {code} state was retained.",
                path,
            )
        )


def _first_unsupported_path(root: Path) -> Path | None:
    for current, directories, files in os.walk(root, followlinks=False, onerror=raise_walk_error):
        current_path = Path(current)
        directories.sort()
        for name in [*directories, *sorted(files)]:
            path = current_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                return path
    return None


def _is_empty_directory(path: Path) -> bool:
    return next(path.iterdir(), None) is None


def _repair_error(artifact: RetiredArtifact, error: OSError) -> DoctorCheck:
    return DoctorCheck(
        "retired",
        f"{artifact.code}_repair_failed",
        Severity.ERROR,
        f"Could not archive the {artifact.label}: {error}",
        artifact.path,
    )
