"""Contracts for doctor models, paths, and baseline orchestration."""

from __future__ import annotations

from pathlib import Path

from basecamp.doctor.models import DoctorCheck, DoctorPaths, DoctorReport, Severity
from basecamp.doctor.service import run_doctor


def test_paths_are_bounded_under_basecamp_root(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)

    assert paths.root == tmp_path / ".pi" / "basecamp"
    assert paths.config == paths.root / "config.json"
    assert paths.config_lock == paths.root / "config.lock"
    assert paths.archive_root == paths.root / "backups" / "doctor"
    assert paths.daemon_db == paths.root / "swarm" / "daemon.db"


def test_report_exit_code_distinguishes_warnings_from_unresolved() -> None:
    report = DoctorReport(
        checks=[DoctorCheck("layout", "warning", Severity.WARNING, "Warning")],
    )
    assert report.exit_code == 0

    report.add_check(DoctorCheck("config", "repair", Severity.REPAIRABLE, "Repair"))
    assert report.exit_code == 1


def test_missing_root_is_healthy_and_read_only(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)

    checked = run_doctor(paths)
    repaired = run_doctor(paths, repair=True)

    for report in (checked, repaired):
        assert report.exit_code == 0
        assert [(check.identifier, check.severity) for check in report.checks] == [
            ("layout.root_missing", Severity.INFO)
        ]
    assert not paths.root.exists()


def test_regular_root_passes_without_writing(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    paths.root.mkdir(parents=True)

    report = run_doctor(paths)

    assert [(check.identifier, check.severity) for check in report.checks] == [("layout.root", Severity.PASS)]
    assert list(paths.root.iterdir()) == []


def test_symlinked_root_is_an_error(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    paths = DoctorPaths.for_home(tmp_path)
    paths.root.parent.mkdir(parents=True)
    paths.root.symlink_to(target, target_is_directory=True)

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert report.checks[0].identifier == "layout.root_symlink"
    assert list(target.iterdir()) == []
