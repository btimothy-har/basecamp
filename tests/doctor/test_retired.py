"""Archive-only cleanup for known retired local state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import basecamp.doctor.retired as retired
from basecamp.doctor.archive import DoctorArchive
from basecamp.doctor.models import DoctorPaths, Severity
from basecamp.doctor.process import DaemonState, DaemonStatus
from basecamp.doctor.service import run_doctor


@pytest.fixture(autouse=True)
def retired_daemon_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retired, "inspect_daemon", lambda *_args, **_kwargs: DaemonStatus(DaemonState.DOWN))


def _checks(report) -> dict[str, Severity]:
    return {check.identifier: check.severity for check in report.checks}


def test_clean_break_artifacts_are_archived_without_import(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    launch_index = paths.workstream_launches / "launch-index.json"
    analysis = paths.companion_analysis / "session.analysis.json"
    claude_db = paths.claude_runtime / "daemon.db"
    for path, content in (
        (launch_index, b'{"launches": ["legacy"]}\n'),
        (analysis, b'{"analysis": "legacy"}\n'),
        (claude_db, b"retired-claude-database"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    checked = run_doctor(paths)

    assert checked.exit_code == 1
    assert _checks(checked)["retired.workstream_launches"] is Severity.REPAIRABLE
    assert _checks(checked)["retired.companion_analysis"] is Severity.REPAIRABLE
    assert _checks(checked)["retired.claude_runtime"] is Severity.REPAIRABLE
    assert launch_index.exists() and analysis.exists() and claude_db.exists()

    repaired = run_doctor(paths, repair=True)

    assert repaired.exit_code == 0
    assert repaired.archive_path is not None
    assert not paths.workstream_launches.exists()
    assert not paths.companion_analysis.exists()
    assert not paths.claude_runtime.exists()
    assert (
        repaired.archive_path / "retired" / "workstream-launches" / "launch-index.json"
    ).read_bytes() == b'{"launches": ["legacy"]}\n'
    assert (
        repaired.archive_path / "retired" / "companion" / "analysis" / "session.analysis.json"
    ).read_bytes() == b'{"analysis": "legacy"}\n'
    assert (repaired.archive_path / "retired" / "claude" / "daemon.db").read_bytes() == b"retired-claude-database"
    manifest = json.loads((repaired.archive_path / "manifest.json").read_text(encoding="utf-8"))
    assert [entry["operation"] for entry in manifest["entries"]] == ["retire", "retire", "retire"]


def test_live_retired_daemon_blocks_only_its_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    (paths.claude_runtime / "daemon.db").parent.mkdir(parents=True)
    (paths.claude_runtime / "daemon.db").write_bytes(b"claude")
    launch_index = paths.workstream_launches / "launch-index.json"
    launch_index.parent.mkdir(parents=True)
    launch_index.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        retired,
        "inspect_daemon",
        lambda *_args, **_kwargs: DaemonStatus(DaemonState.LIVE, protocol=1),
    )

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert not paths.workstream_launches.exists()
    assert paths.claude_runtime.exists()
    assert report.archive_path is not None
    assert _checks(report)["retired.claude_runtime_live"] is Severity.ERROR


def test_unknown_and_excluded_state_is_reported_and_retained(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    unknown = paths.root / "user-script.sh"
    profile = paths.browser_profile / "cookies"
    output = paths.browser_output / "screenshot.png"
    for path in (unknown, profile, output):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 0
    assert unknown.exists() and profile.exists() and output.exists()
    assert report.archive_path is None
    assert _checks(report)["unknown.top_level_1"] is Severity.INFO
    assert _checks(report)["excluded.browser_profile"] is Severity.INFO


def test_empty_workspace_wrapper_is_archived_but_unknown_content_is_not(tmp_path: Path) -> None:
    empty_paths = DoctorPaths.for_home(tmp_path / "empty")
    empty_paths.workspace.mkdir(parents=True)

    empty_report = run_doctor(empty_paths, repair=True)

    assert empty_report.exit_code == 0
    assert not empty_paths.workspace.exists()
    assert empty_report.archive_path is not None

    unknown_paths = DoctorPaths.for_home(tmp_path / "unknown")
    unknown = unknown_paths.workspace / "keep.txt"
    unknown.parent.mkdir(parents=True)
    unknown.write_text("keep", encoding="utf-8")

    unknown_report = run_doctor(unknown_paths, repair=True)

    assert unknown_report.exit_code == 0
    assert unknown.exists()
    assert unknown_report.archive_path is None
    assert _checks(unknown_report)["retired.workspace_unknown"] is Severity.WARNING


def test_retirement_failure_is_partial_and_recoverable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    launch_index = paths.workstream_launches / "launch-index.json"
    analysis = paths.companion_analysis / "session.json"
    for path in (launch_index, analysis):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    original_retire = DoctorArchive.retire

    def fail_one(self: DoctorArchive, source: Path, relative: Path) -> Path:
        if source == paths.workstream_launches:
            raise OSError
        return original_retire(self, source, relative)

    monkeypatch.setattr(DoctorArchive, "retire", fail_one)

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert launch_index.exists()
    assert not paths.companion_analysis.exists()
    assert report.archive_path is not None
    assert _checks(report)["retired.workstream_launches"] is Severity.REPAIRABLE
    assert _checks(report)["retired.workstream_launches_repair_failed"] is Severity.ERROR
    assert (report.archive_path / "retired" / "companion" / "analysis" / "session.json").exists()


def test_retired_tree_with_symlink_is_never_archived(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    target = tmp_path / "outside"
    target.write_text("outside", encoding="utf-8")
    paths.workstream_launches.mkdir(parents=True)
    (paths.workstream_launches / "link").symlink_to(target)

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert paths.workstream_launches.exists()
    assert target.read_text(encoding="utf-8") == "outside"
    assert report.archive_path is None
