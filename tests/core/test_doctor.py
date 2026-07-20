"""Tests for ``basecamp doctor`` — checks, opt-in fix, and runtime reclaim."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from basecamp.core.doctor import run_doctor
from basecamp.core.doctor.checks import gather
from basecamp.core.doctor.checks import runtime as runtime_check
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.doctor.locations import Locations
from basecamp.core.settings import CONFIG_VERSION, Settings

_DAY = 86400


@pytest.fixture
def env(tmp_path: Path) -> tuple[Settings, Locations]:
    """A Settings + Locations pair rooted at an isolated temp home."""
    home = tmp_path / "home"
    basecamp_dir = home / ".pi" / "basecamp"
    basecamp_dir.mkdir(parents=True)
    return Settings(basecamp_dir / "config.json"), Locations(home=home, basecamp_dir=basecamp_dir)


def _write(settings: Settings, document: dict) -> None:
    settings.path.write_text(json.dumps(document))


def _read(settings: Settings) -> dict:
    return json.loads(settings.path.read_text())


def _scaffold(locations: Locations) -> None:
    for path in locations.scaffold_dirs:
        path.mkdir(parents=True, exist_ok=True)


def _all_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("basecamp.core.prereqs.is_available", lambda _command: True)


def _in(group: str, findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if finding.group == group]


# --- integrity ----------------------------------------------------------------


def test_absent_config_reports_not_set_up(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    findings = gather(settings, locations, stale_days=30)
    config = _in("Config", findings)
    assert len(config) == 1
    assert config[0].severity is Severity.WARNING
    assert "not set up" in config[0].summary


def test_corrupt_config_is_error_and_skips_config_checks(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    settings.path.write_text("{ this is not json")
    findings = gather(settings, locations, stale_days=30)
    config = _in("Config", findings)
    assert len(config) == 1
    assert config[0].severity is Severity.ERROR
    assert "not valid JSON" in config[0].summary
    assert not _in("References", findings)  # config-derived checks skipped


def test_non_object_config_is_error(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    settings.path.write_text("[1, 2, 3]")
    config = _in("Config", gather(settings, locations, stale_days=30))
    assert config and config[0].severity is Severity.ERROR
    assert "not an object" in config[0].summary


def test_missing_version_is_fixable(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _write(settings, {"projects": {}})
    findings = _in("Config", gather(settings, locations, stale_days=30))
    version_findings = [finding for finding in findings if "version" in finding.summary]
    assert version_findings and version_findings[0].remedy is Remedy.FIX


def test_run_fix_stamps_version(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _write(settings, {"projects": {}})
    _all_available(monkeypatch)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert _read(settings)["version"] == CONFIG_VERSION


def test_invalid_project_record_is_error(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _write(settings, {"version": CONFIG_VERSION, "projects": {"bad": {"description": "no repo_root"}}})
    config = _in("Config", gather(settings, locations, stale_days=30))
    assert any(finding.severity is Severity.ERROR and "projects.bad" in finding.summary for finding in config)


# --- references ---------------------------------------------------------------


def test_missing_repo_root_is_error(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "projects": {"demo": {"repo_root": "nope/gone"}}})
    refs = _in("References", gather(settings, locations, stale_days=30))
    assert any(finding.severity is Severity.ERROR and "repo_root" in finding.summary for finding in refs)


def test_valid_git_repo_root_passes(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _scaffold(locations)
    repo = locations.home / "work" / "demo"
    (repo / ".git").mkdir(parents=True)
    _write(settings, {"version": CONFIG_VERSION, "projects": {"demo": {"repo_root": "work/demo"}}})
    assert not _in("References", gather(settings, locations, stale_days=30))


def test_repo_root_without_git_is_warning(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _scaffold(locations)
    (locations.home / "work" / "demo").mkdir(parents=True)
    _write(settings, {"version": CONFIG_VERSION, "projects": {"demo": {"repo_root": "work/demo"}}})
    refs = _in("References", gather(settings, locations, stale_days=30))
    assert len(refs) == 1
    assert refs[0].severity is Severity.WARNING and "not a git repository" in refs[0].summary


def test_missing_scaffold_dirs_fixable(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _write(settings, {"version": CONFIG_VERSION})
    _all_available(monkeypatch)
    refs = _in("References", gather(settings, locations, stale_days=30))
    assert refs and refs[0].remedy is Remedy.FIX
    run_doctor(fix=True, settings=settings, locations=locations)
    assert all(path.is_dir() for path in locations.scaffold_dirs)


# --- unused config ------------------------------------------------------------


def test_installed_modules_pruned_by_fix(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "installed_modules": ["old"]})
    _all_available(monkeypatch)
    unused = _in("Unused config", gather(settings, locations, stale_days=30))
    assert any(finding.remedy is Remedy.FIX for finding in unused)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert "installed_modules" not in _read(settings)


def test_unknown_key_reported_not_removed(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "mystery": {"keep": True}})
    _all_available(monkeypatch)
    unused = _in("Unused config", gather(settings, locations, stale_days=30))
    assert any(finding.remedy is Remedy.NONE and "mystery" in finding.summary for finding in unused)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert _read(settings)["mystery"] == {"keep": True}  # authored data left intact


def test_empty_environment_pruned_by_fix(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "environments": {"org/repo": {"setup": "  "}}})
    _all_available(monkeypatch)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert _read(settings)["environments"] == {}


def test_malformed_alias_pruned_by_fix(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "model_aliases": {"fast": "haiku", "bad": 123}})
    _all_available(monkeypatch)
    unused = _in("Unused config", gather(settings, locations, stale_days=30))
    assert any(finding.remedy is Remedy.FIX for finding in unused)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert _read(settings)["model_aliases"] == {"fast": "haiku"}


def test_legacy_overrides_reported_only(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    legacy = locations.legacy_overrides_dir / "context"
    legacy.mkdir(parents=True)
    (legacy / "old.md").write_text("stale")
    _write(settings, {"version": CONFIG_VERSION})
    _all_available(monkeypatch)
    unused = _in("Unused config", gather(settings, locations, stale_days=30))
    assert any(finding.remedy is Remedy.NONE and "pre-rearchitecture" in finding.summary for finding in unused)
    run_doctor(fix=True, settings=settings, locations=locations)
    assert (legacy / "old.md").exists()  # authored content never auto-deleted


# --- runtime ------------------------------------------------------------------


def _make_profile(locations: Locations, *, age_days: int) -> Path:
    profile = locations.browser_profile
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("session")
    old = time.time() - age_days * _DAY
    os.utime(profile / "Cookies", (old, old))
    os.utime(profile, (old, old))
    return profile


def test_stale_profile_is_cleanable(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _make_profile(locations, age_days=45)
    runtime = _in("Runtime", gather(settings, locations, stale_days=30))
    assert len(runtime) == 1
    assert runtime[0].remedy is Remedy.CLEAN and "reclaim" in (runtime[0].action or "")


def test_warm_profile_is_kept(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    _make_profile(locations, age_days=3)
    assert not _in("Runtime", gather(settings, locations, stale_days=30))


def test_held_profile_is_kept(env: tuple[Settings, Locations]) -> None:
    settings, locations = env
    profile = _make_profile(locations, age_days=99)
    os.symlink(f"host-{os.getpid()}", profile / "SingletonLock")  # live pid holds it
    assert runtime_check.classify_profile(profile).in_use is True
    assert not _in("Runtime", gather(settings, locations, stale_days=30))


def test_clean_reclaims_after_confirmation(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION})
    profile = _make_profile(locations, age_days=60)
    _all_available(monkeypatch)
    monkeypatch.setattr("basecamp.core.doctor.run.questionary.confirm", lambda *_a, **_k: _Yes())
    run_doctor(clean=True, settings=settings, locations=locations)
    assert not profile.exists()


def test_clean_skips_when_declined(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION})
    profile = _make_profile(locations, age_days=60)
    _all_available(monkeypatch)
    monkeypatch.setattr("basecamp.core.doctor.run.questionary.confirm", lambda *_a, **_k: _No())
    run_doctor(clean=True, settings=settings, locations=locations)
    assert profile.exists()  # declined → left in place


# --- exit codes ---------------------------------------------------------------


def test_exit_zero_when_clean(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION})
    _all_available(monkeypatch)
    assert run_doctor(settings=settings, locations=locations) == 0


def test_exit_one_on_error(env: tuple[Settings, Locations], monkeypatch: pytest.MonkeyPatch) -> None:
    settings, locations = env
    _scaffold(locations)
    _write(settings, {"version": CONFIG_VERSION, "projects": {"demo": {"repo_root": "gone/nowhere"}}})
    _all_available(monkeypatch)
    assert run_doctor(settings=settings, locations=locations) == 1


class _Yes:
    def ask(self) -> bool:
        return True


class _No:
    def ask(self) -> bool:
        return False
