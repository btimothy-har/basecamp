"""Doctor orchestration across config, layout, and hub checks."""

from __future__ import annotations

import stat

from .models import DoctorCheck, DoctorPaths, DoctorReport, Severity


def run_doctor(paths: DoctorPaths, *, repair: bool = False) -> DoctorReport:  # noqa: ARG001
    """Inspect Basecamp local state; repair providers are added by each owner."""
    report = DoctorReport()
    try:
        mode = paths.root.lstat().st_mode
    except FileNotFoundError:
        report.add_check(
            DoctorCheck(
                section="layout",
                code="root_missing",
                severity=Severity.INFO,
                message="Basecamp local state is not initialized.",
                path=paths.root,
            )
        )
        return report
    except OSError as exc:
        report.add_check(
            DoctorCheck(
                section="layout",
                code="root_unreadable",
                severity=Severity.ERROR,
                message=f"Could not inspect Basecamp local state: {exc}",
                path=paths.root,
            )
        )
        return report

    if stat.S_ISLNK(mode):
        report.add_check(
            DoctorCheck(
                section="layout",
                code="root_symlink",
                severity=Severity.ERROR,
                message="Basecamp local-state root is a symlink; repair is disabled.",
                path=paths.root,
            )
        )
    elif not stat.S_ISDIR(mode):
        report.add_check(
            DoctorCheck(
                section="layout",
                code="root_type",
                severity=Severity.ERROR,
                message="Basecamp local-state root is not a directory.",
                path=paths.root,
            )
        )
    else:
        report.add_check(
            DoctorCheck(
                section="layout",
                code="root",
                severity=Severity.PASS,
                message="Basecamp local-state root is readable.",
                path=paths.root,
            )
        )
    return report
