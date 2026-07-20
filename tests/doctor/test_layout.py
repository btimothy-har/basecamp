"""Customization layout migration and collision handling."""

from __future__ import annotations

from pathlib import Path

from basecamp.doctor.models import DoctorPaths, Severity
from basecamp.doctor.service import run_doctor


def _layout_checks(report) -> dict[str, Severity]:
    return {check.identifier: check.severity for check in report.checks if check.section == "layout"}


def test_legacy_customizations_copy_then_archive(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    source = paths.legacy_context / "nested" / "project.md"
    source.parent.mkdir(parents=True)
    source.write_text("context\n", encoding="utf-8")

    checked = run_doctor(paths)

    assert checked.exit_code == 1
    assert source.exists()
    assert _layout_checks(checked)["layout.context_legacy"] is Severity.REPAIRABLE

    repaired = run_doctor(paths, repair=True)
    second = run_doctor(paths, repair=True)

    assert repaired.exit_code == 0
    assert repaired.archive_path is not None
    assert not paths.legacy_context.exists()
    assert (paths.context / "nested" / "project.md").read_text(encoding="utf-8") == "context\n"
    assert (repaired.archive_path / "retired" / "workspace" / "context" / "nested" / "project.md").exists()
    assert second.exit_code == 0
    assert second.archive_path is None


def test_identical_current_customization_allows_legacy_archive(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    current = paths.styles / "engineering.md"
    legacy = paths.legacy_styles / "engineering.md"
    current.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    current.write_text("style\n", encoding="utf-8")
    legacy.write_text("style\n", encoding="utf-8")

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 0
    assert current.read_text(encoding="utf-8") == "style\n"
    assert not paths.legacy_styles.exists()


def test_differing_customization_is_never_overwritten(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    current = paths.prompts / "environment.md"
    legacy = paths.legacy_prompts / "environment.md"
    current.parent.mkdir(parents=True)
    legacy.parent.mkdir(parents=True)
    current.write_text("current\n", encoding="utf-8")
    legacy.write_text("legacy\n", encoding="utf-8")

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert current.read_text(encoding="utf-8") == "current\n"
    assert legacy.read_text(encoding="utf-8") == "legacy\n"
    assert report.archive_path is None
    assert _layout_checks(report)["layout.prompts_conflict"] is Severity.ERROR


def test_legacy_tree_with_symlink_is_retained(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    target = tmp_path / "outside.md"
    target.write_text("outside\n", encoding="utf-8")
    paths.legacy_context.mkdir(parents=True)
    (paths.legacy_context / "link.md").symlink_to(target)

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert (paths.legacy_context / "link.md").is_symlink()
    assert target.read_text(encoding="utf-8") == "outside\n"
    assert report.archive_path is None


def test_excluded_browser_profile_is_untouched(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    marker = paths.browser_profile / "marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("keep", encoding="utf-8")

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 0
    assert marker.read_text(encoding="utf-8") == "keep"
    assert report.archive_path is None
