"""Unified config diagnosis and non-destructive legacy convergence."""

from __future__ import annotations

import copy
import json
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from basecamp.core.cli.config_schema import validate_document, validate_section
from basecamp.core.exceptions import LauncherError
from basecamp.core.model_aliases import normalize_aliases
from basecamp.core.settings import CONFIG_VERSION, Settings

from .archive import DoctorArchive
from .models import DoctorCheck, DoctorPaths, DoctorReport, RepairAction, RepairKind, Severity

_RETIRED_ROOT_KEYS = frozenset({"installed_modules", "observer", "worktree_branch_prefix"})


@dataclass(frozen=True)
class LegacySection:
    path: Path
    section: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ConfigState:
    report: DoctorReport
    document: dict[str, Any] | None
    candidate: dict[str, Any] | None
    raw: bytes | None
    legacy: tuple[LegacySection, ...]
    needs_mode_repair: bool

    @property
    def needs_write(self) -> bool:
        return self.candidate is not None and self.candidate != self.document


def inspect_config(paths: DoctorPaths) -> DoctorReport:
    """Inspect current and immediately-prior config schemas without writing."""
    return _build_state(paths).report


def repair_config(paths: DoctorPaths, archive: DoctorArchive) -> list[DoctorCheck]:
    """Apply eligible config convergence and archive represented legacy files."""
    state = _build_state(paths)
    errors: list[DoctorCheck] = []
    if state.candidate is None:
        return errors
    if state.needs_write:
        try:
            _write_candidate(paths, archive)
        except (LauncherError, OSError, ValueError) as exc:
            errors.append(_repair_error("write_failed", f"Config repair failed: {exc}", paths.config))
            return errors
    elif state.needs_mode_repair:
        try:
            paths.config.chmod(0o600)
        except OSError as exc:
            errors.append(_repair_error("mode_failed", f"Config permission repair failed: {exc}", paths.config))

    try:
        _archive_represented_sources(paths, archive)
    except (LauncherError, OSError, ValueError) as exc:
        errors.append(_repair_error("archive_failed", f"Legacy config archival failed: {exc}", paths.root))
    return errors


def _build_state(paths: DoctorPaths) -> ConfigState:
    report = DoctorReport()
    document, raw, current_error = _read_current(paths.config)
    legacy = _read_legacy_sections(paths, report)

    if current_error is not None:
        report.add_check(
            DoctorCheck("config", "invalid", Severity.ERROR, current_error, paths.config),
        )
        _report_blocked_legacy(legacy, report)
        return ConfigState(report, None, None, raw, legacy, needs_mode_repair=False)

    if document is None and not legacy:
        report.add_check(
            DoctorCheck(
                "config",
                "missing",
                Severity.INFO,
                "Unified config is not initialized.",
                paths.config,
            )
        )
        return ConfigState(report, None, None, raw, legacy, needs_mode_repair=False)

    source = document or {}
    try:
        candidate = _build_candidate(source, legacy)
    except LauncherError as exc:
        report.add_check(
            DoctorCheck("config", "schema", Severity.ERROR, str(exc), paths.config),
        )
        _report_legacy_conflicts(source, legacy, report)
        return ConfigState(report, document, None, raw, legacy, needs_mode_repair=False)

    if candidate != document:
        report.add_check(
            DoctorCheck(
                "config",
                "schema",
                Severity.REPAIRABLE,
                "Unified config can be converged to the current schema.",
                paths.config,
            )
        )
        report.add_action(
            RepairAction(
                code="config.converge",
                kind=RepairKind.CONFIG,
                description="Back up and converge the unified config document.",
                paths=(paths.config,),
            )
        )
    else:
        report.add_check(
            DoctorCheck("config", "schema", Severity.PASS, "Unified config schema is current.", paths.config),
        )

    mode_repair = document is not None and stat.S_IMODE(paths.config.stat().st_mode) != 0o600
    if mode_repair:
        report.add_check(
            DoctorCheck(
                "config",
                "permissions",
                Severity.REPAIRABLE,
                "Unified config permissions can be restricted to owner-only.",
                paths.config,
            )
        )
        report.add_action(
            RepairAction(
                code="config.permissions",
                kind=RepairKind.CONFIG,
                description="Restrict unified config permissions to 0600.",
                paths=(paths.config,),
            )
        )
    else:
        report.add_check(
            DoctorCheck("config", "permissions", Severity.PASS, "Unified config permissions are private.", paths.config)
        )

    _report_legacy_status(candidate, legacy, report)
    return ConfigState(report, document, candidate, raw, legacy, mode_repair)


def _read_current(path: Path) -> tuple[dict[str, Any] | None, bytes | None, str | None]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, None, None
    except OSError as exc:
        return None, None, f"Could not inspect unified config: {exc}"

    if stat.S_ISLNK(mode):
        return None, None, "Unified config is a symlink; automatic repair is disabled."
    if not stat.S_ISREG(mode):
        return None, None, "Unified config is not a regular file."
    try:
        raw = path.read_bytes()
        parsed = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"Unified config is not valid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, raw, "Unified config must be a JSON object."
    return parsed, raw, None


def _read_legacy_sections(paths: DoctorPaths, report: DoctorReport) -> tuple[LegacySection, ...]:
    sections: list[LegacySection] = []
    for path, section, payload_key in (
        (paths.legacy_projects, "projects", "projects"),
        (paths.legacy_aliases, "model_aliases", "aliases"),
    ):
        payload, error = _read_legacy_file(path, section, payload_key)
        if error is not None:
            report.add_check(DoctorCheck("config", f"legacy_{section}", Severity.ERROR, error, path))
        elif payload is not None:
            sections.append(LegacySection(path=path, section=section, payload=payload))
    return tuple(sections)


def _read_legacy_file(path: Path, section: str, payload_key: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None, None
    except OSError as exc:
        return None, f"Could not inspect legacy {section} config: {exc}"
    if stat.S_ISLNK(mode):
        return None, f"Legacy {section} config is a symlink; repair is disabled."
    if not stat.S_ISREG(mode):
        return None, f"Legacy {section} config is not a regular file."
    try:
        parsed = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"Legacy {section} config is invalid JSON: {exc}"
    if not isinstance(parsed, dict):
        return None, f"Legacy {section} config must be a JSON object."
    version = parsed.get("version")
    if version is not None and (
        isinstance(version, bool) or not isinstance(version, int) or version < 0 or version > 1
    ):
        return None, f"Legacy {section} config has an unsupported version."
    try:
        raw_payload = parsed.get(payload_key)
        if section == "projects":
            wrapper = {"projects": copy.deepcopy(raw_payload)}
            _migrate_project_dirs(wrapper)
            raw_payload = wrapper["projects"]
        payload = validate_section(section, raw_payload)
    except LauncherError as exc:
        return None, f"Legacy {section} config is invalid: {exc}"
    return payload, None


def _build_candidate(document: dict[str, Any], legacy: tuple[LegacySection, ...]) -> dict[str, Any]:
    candidate = copy.deepcopy(document)
    _validate_version(candidate)
    _migrate_root_models(candidate)
    _migrate_project_dirs(candidate)
    for key in _RETIRED_ROOT_KEYS:
        candidate.pop(key, None)
    for source in legacy:
        current = candidate.get(source.section)
        if current is None:
            candidate[source.section] = copy.deepcopy(source.payload)
            continue
        normalized = validate_section(source.section, current)
        if not _is_subset(source.payload, normalized):
            msg = f"Legacy {source.section} conflicts with the unified config; resolve it manually."
            raise LauncherError(msg)
    candidate["version"] = CONFIG_VERSION
    changed = candidate != document
    normalized = validate_document(candidate)
    return normalized if changed else candidate


def _validate_version(document: dict[str, Any]) -> None:
    version = document.get("version")
    if version is None:
        return
    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        msg = "Config version must be a non-negative integer."
        raise LauncherError(msg)
    if version > CONFIG_VERSION:
        msg = f"Config version {version} is newer than supported version {CONFIG_VERSION}; repair is disabled."
        raise LauncherError(msg)


def _migrate_root_models(document: dict[str, Any]) -> None:
    if "models" not in document:
        return
    legacy = normalize_aliases(document["models"])
    current = document.get("model_aliases")
    if current is None:
        document["model_aliases"] = legacy
    else:
        merged = normalize_aliases(current)
        for alias, model in legacy.items():
            if alias in merged and merged[alias] != model:
                msg = "Legacy models conflict with model_aliases; resolve them manually."
                raise LauncherError(msg)
            merged[alias] = model
        document["model_aliases"] = merged
    document.pop("models")


def _migrate_project_dirs(document: dict[str, Any]) -> None:
    projects = document.get("projects")
    if not isinstance(projects, dict):
        return
    for name, value in projects.items():
        if not isinstance(value, dict) or "dirs" not in value:
            continue
        dirs = value.get("dirs")
        if not isinstance(dirs, list) or not all(isinstance(item, str) for item in dirs):
            msg = f"Legacy projects.{name}.dirs must be a list of strings."
            raise LauncherError(msg)
        repo_root = value.get("repo_root")
        additional = value.get("additional_dirs")
        if repo_root is None:
            if not dirs:
                msg = f"Legacy projects.{name}.dirs cannot be empty without repo_root."
                raise LauncherError(msg)
            value["repo_root"] = dirs[0]
        elif dirs and repo_root != dirs[0]:
            msg = f"Legacy projects.{name}.dirs conflicts with repo_root."
            raise LauncherError(msg)
        if additional is None:
            value["additional_dirs"] = dirs[1:] if dirs else []
        elif dirs and additional != dirs[1:]:
            msg = f"Legacy projects.{name}.dirs conflicts with additional_dirs."
            raise LauncherError(msg)
        value.pop("dirs")


def _write_candidate(paths: DoctorPaths, archive: DoctorArchive) -> None:
    settings = Settings(paths.config)

    def mutate(data: dict[str, Any]) -> bool:
        document, raw, error = _read_current(paths.config)
        if error is not None:
            raise LauncherError(error)
        current = document or {}
        if current != data:
            msg = "Unified config changed while the doctor held its lock."
            raise LauncherError(msg)
        legacy = _read_legacy_sections(paths, DoctorReport())
        candidate = _build_candidate(current, legacy)
        if candidate == document:
            return False
        if raw is not None:
            archive.backup_bytes(paths.config, raw, Path("config.json"))
        data.clear()
        data.update(candidate)
        return True

    settings.update_if_changed(mutate)


def _archive_represented_sources(paths: DoctorPaths, archive: DoctorArchive) -> None:
    document, _raw, error = _read_current(paths.config)
    if error is not None or document is None:
        return
    legacy = _read_legacy_sections(paths, DoctorReport())
    normalized = validate_document(document)
    for source in legacy:
        current = normalized.get(source.section)
        if isinstance(current, dict) and _is_subset(source.payload, current):
            archive.retire(source.path, source.path.relative_to(paths.root))


def _section_contains(section: str, expected: dict[str, Any], actual: Any) -> bool:
    try:
        normalized = validate_section(section, actual)
    except LauncherError:
        return False
    return _is_subset(expected, normalized)


def _is_subset(expected: dict[str, Any], actual: Any) -> bool:
    return isinstance(actual, dict) and all(key in actual and actual[key] == value for key, value in expected.items())


def _report_legacy_status(
    candidate: dict[str, Any],
    legacy: tuple[LegacySection, ...],
    report: DoctorReport,
) -> None:
    for source in legacy:
        current = candidate.get(source.section)
        if not _section_contains(source.section, source.payload, current):
            report.add_check(
                DoctorCheck(
                    "config",
                    f"legacy_{source.section}_conflict",
                    Severity.ERROR,
                    f"Legacy {source.section} differs from unified config.",
                    source.path,
                )
            )
            continue
        report.add_check(
            DoctorCheck(
                "config",
                f"legacy_{source.section}",
                Severity.REPAIRABLE,
                f"Legacy {source.section} config can be archived after verification.",
                source.path,
            )
        )
        report.add_action(
            RepairAction(
                code=f"config.archive_{source.section}",
                kind=RepairKind.ARCHIVE,
                description=f"Archive represented legacy {source.section} config.",
                paths=(source.path,),
            )
        )


def _report_blocked_legacy(legacy: tuple[LegacySection, ...], report: DoctorReport) -> None:
    for source in legacy:
        report.add_check(
            DoctorCheck(
                "config",
                f"legacy_{source.section}_blocked",
                Severity.WARNING,
                "Legacy config is retained until the unified config is valid.",
                source.path,
            )
        )


def _report_legacy_conflicts(
    document: dict[str, Any],
    legacy: tuple[LegacySection, ...],
    report: DoctorReport,
) -> None:
    for source in legacy:
        current = document.get(source.section)
        if current is not None and not _section_contains(source.section, source.payload, current):
            report.add_check(
                DoctorCheck(
                    "config",
                    f"legacy_{source.section}_conflict",
                    Severity.ERROR,
                    f"Legacy {source.section} differs from unified config.",
                    source.path,
                )
            )


def _repair_error(code: str, message: str, path: Path) -> DoctorCheck:
    return DoctorCheck("config", code, Severity.ERROR, message, path)
