"""Unified config diagnosis and repair behavior."""

from __future__ import annotations

import json
from pathlib import Path

from basecamp.doctor.models import DoctorPaths, Severity
from basecamp.doctor.service import run_doctor


def _write_json(path: Path, value: object) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"{json.dumps(value, indent=2)}\n".encode()
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _config_checks(report) -> dict[str, Severity]:
    return {check.identifier: check.severity for check in report.checks if check.section == "config"}


def test_check_current_config_is_read_only(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    original = _write_json(
        paths.config,
        {
            "version": 1,
            "projects": {"demo": {"repo_root": "src/demo"}},
            "custom": {"preserve": True},
        },
    )

    report = run_doctor(paths)

    assert report.exit_code == 0
    assert _config_checks(report)["config.schema"] is Severity.PASS
    assert paths.config.read_bytes() == original
    assert not paths.config_lock.exists()
    assert not paths.archive_root.exists()


def test_repair_converges_supported_legacy_document_and_is_idempotent(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    original = _write_json(
        paths.config,
        {
            "version": 0,
            "install_dir": "/repo",
            "models": {" fast ": " model-a "},
            "installed_modules": ["core"],
            "observer": {"mode": "off"},
            "worktree_branch_prefix": "bt/",
            "projects": {"demo": {"dirs": ["src/demo", "src/shared"]}},
            "custom": {"preserve": True},
        },
    )

    checked = run_doctor(paths)
    repaired = run_doctor(paths, repair=True)
    after_first = paths.config.read_bytes()
    second = run_doctor(paths, repair=True)

    assert checked.exit_code == 1
    assert _config_checks(checked)["config.schema"] is Severity.REPAIRABLE
    assert repaired.exit_code == 0
    assert repaired.archive_path is not None
    assert paths.config_lock.exists()
    assert json.loads(after_first) == {
        "version": 1,
        "install_dir": "/repo",
        "projects": {
            "demo": {
                "repo_root": "src/demo",
                "additional_dirs": ["src/shared"],
                "description": "",
                "working_style": None,
                "context": None,
            }
        },
        "custom": {"preserve": True},
        "model_aliases": {"fast": "model-a"},
    }
    assert (repaired.archive_path / "backups" / "config.json").read_bytes() == original
    assert second.exit_code == 0
    assert second.archive_path is None
    assert paths.config.read_bytes() == after_first


def test_corrupt_and_forward_config_are_never_rewritten(tmp_path: Path) -> None:
    for name, content in (
        ("corrupt", b"{not-json\n"),
        ("forward", b'{"version": 2, "future": {"keep": true}}\n'),
    ):
        home = tmp_path / name
        paths = DoctorPaths.for_home(home)
        paths.config.parent.mkdir(parents=True)
        paths.config.write_bytes(content)

        report = run_doctor(paths, repair=True)

        assert report.exit_code == 1
        assert paths.config.read_bytes() == content
        assert report.archive_path is None


def test_repair_restricts_config_permissions_without_content_change(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    original = _write_json(paths.config, {"version": 1, "custom": {"keep": True}})
    paths.config.chmod(0o644)

    checked = run_doctor(paths)
    repaired = run_doctor(paths, repair=True)

    assert _config_checks(checked)["config.permissions"] is Severity.REPAIRABLE
    assert repaired.exit_code == 0
    assert paths.config.read_bytes() == original
    assert paths.config.stat().st_mode & 0o777 == 0o600
    assert repaired.archive_path is None


def test_equivalent_legacy_section_with_implicit_defaults_is_archived(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    _write_json(
        paths.config,
        {"version": 1, "projects": {"demo": {"repo_root": "src/demo"}}},
    )
    _write_json(
        paths.legacy_projects,
        {"version": 1, "projects": {"demo": {"repo_root": "src/demo"}}},
    )

    checked = run_doctor(paths)
    repaired = run_doctor(paths, repair=True)

    assert _config_checks(checked)["config.legacy_projects"] is Severity.REPAIRABLE
    assert repaired.exit_code == 0
    assert not paths.legacy_projects.exists()


def test_standalone_legacy_sections_import_then_archive(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    _write_json(paths.config, {"version": 1, "custom": {"keep": True}})
    _write_json(
        paths.legacy_projects,
        {"version": 1, "projects": {"demo": {"dirs": ["src/demo", "src/shared"]}}},
    )
    _write_json(paths.legacy_aliases, {"version": 1, "aliases": {"fast": "model-a"}})

    checked = run_doctor(paths)

    assert checked.exit_code == 1
    assert paths.legacy_projects.exists()
    assert paths.legacy_aliases.exists()

    repaired = run_doctor(paths, repair=True)

    assert repaired.exit_code == 0
    assert repaired.archive_path is not None
    assert not paths.legacy_projects.exists()
    assert not paths.legacy_aliases.exists()
    document = json.loads(paths.config.read_text(encoding="utf-8"))
    assert document["custom"] == {"keep": True}
    assert document["projects"]["demo"]["repo_root"] == "src/demo"
    assert document["projects"]["demo"]["additional_dirs"] == ["src/shared"]
    assert document["model_aliases"] == {"fast": "model-a"}
    assert (repaired.archive_path / "retired" / "workspace" / "projects.json").exists()
    assert (repaired.archive_path / "retired" / "core" / "model-aliases.json").exists()


def test_conflicting_legacy_section_stays_in_place(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    original = _write_json(
        paths.config,
        {"version": 1, "projects": {"demo": {"repo_root": "current"}}},
    )
    _write_json(
        paths.legacy_projects,
        {"version": 1, "projects": {"demo": {"repo_root": "legacy"}}},
    )

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert paths.config.read_bytes() == original
    assert paths.legacy_projects.exists()
    assert report.archive_path is None
    assert _config_checks(report)["config.legacy_projects_conflict"] is Severity.ERROR


def test_invalid_legacy_file_does_not_block_valid_current_config(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    original = _write_json(paths.config, {"projects": {"demo": {"repo_root": "current"}}})
    paths.legacy_aliases.parent.mkdir(parents=True)
    paths.legacy_aliases.write_text("not json", encoding="utf-8")

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert json.loads(paths.config.read_text(encoding="utf-8"))["version"] == 1
    assert paths.legacy_aliases.exists()
    assert report.archive_path is not None
    assert (report.archive_path / "backups" / "config.json").read_bytes() == original


def test_forward_config_never_archives_legacy_sources(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    _write_json(
        paths.config,
        {"version": 2, "projects": {"demo": {"repo_root": "src/demo"}}},
    )
    _write_json(
        paths.legacy_projects,
        {"version": 1, "projects": {"demo": {"repo_root": "src/demo"}}},
    )

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert paths.legacy_projects.exists()
    assert report.archive_path is None


def test_symlinked_legacy_config_is_not_followed(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    _write_json(paths.config, {"version": 1})
    target = tmp_path / "aliases.json"
    _write_json(target, {"version": 1, "aliases": {"fast": "model"}})
    paths.legacy_aliases.parent.mkdir(parents=True)
    paths.legacy_aliases.symlink_to(target)

    report = run_doctor(paths, repair=True)

    assert report.exit_code == 1
    assert paths.legacy_aliases.is_symlink()
    assert target.exists()
    assert report.archive_path is None
