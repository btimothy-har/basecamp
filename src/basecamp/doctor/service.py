"""Doctor orchestration across config, layout, and hub checks."""

from __future__ import annotations

import stat

from .archive import DoctorArchive
from .config import inspect_config, repair_config
from .hub import inspect_hub, repair_hub
from .layout import inspect_customization_layout, repair_customization_layout
from .models import DoctorCheck, DoctorPaths, DoctorReport, Severity


def run_doctor(paths: DoctorPaths, *, repair: bool = False) -> DoctorReport:
    """Inspect local state and optionally apply eligible repairs before rechecking."""
    report, can_continue = _inspect(paths)
    if not repair or not can_continue:
        return report

    archive = DoctorArchive(paths)
    repair_errors = [
        *repair_config(paths, archive),
        *repair_customization_layout(paths, archive),
        *repair_hub(paths, archive),
    ]
    final, _can_continue = _inspect(paths)
    final.checks.extend(repair_errors)
    final.archive_path = archive.path if archive.has_entries else None
    final.repair_attempted = bool(report.actions)
    return final


def _inspect(paths: DoctorPaths) -> tuple[DoctorReport, bool]:
    report = DoctorReport()
    root_check, can_continue = _inspect_root(paths)
    report.add_check(root_check)
    if can_continue:
        report.extend(inspect_config(paths))
        report.extend(inspect_customization_layout(paths))
        report.extend(inspect_hub(paths))
    return report, can_continue


def _inspect_root(paths: DoctorPaths) -> tuple[DoctorCheck, bool]:
    try:
        mode = paths.root.lstat().st_mode
    except FileNotFoundError:
        return (
            DoctorCheck(
                section="layout",
                code="root_missing",
                severity=Severity.INFO,
                message="Basecamp local state is not initialized.",
                path=paths.root,
            ),
            False,
        )
    except OSError as exc:
        return (
            DoctorCheck(
                section="layout",
                code="root_unreadable",
                severity=Severity.ERROR,
                message=f"Could not inspect Basecamp local state: {exc}",
                path=paths.root,
            ),
            False,
        )

    if stat.S_ISLNK(mode):
        return (
            DoctorCheck(
                section="layout",
                code="root_symlink",
                severity=Severity.ERROR,
                message="Basecamp local-state root is a symlink; repair is disabled.",
                path=paths.root,
            ),
            False,
        )
    if not stat.S_ISDIR(mode):
        return (
            DoctorCheck(
                section="layout",
                code="root_type",
                severity=Severity.ERROR,
                message="Basecamp local-state root is not a directory.",
                path=paths.root,
            ),
            False,
        )
    return (
        DoctorCheck(
            section="layout",
            code="root",
            severity=Severity.PASS,
            message="Basecamp local-state root is readable.",
            path=paths.root,
        ),
        True,
    )
