"""Customization-directory diagnosis and collision-safe migration."""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .archive import DoctorArchive, hash_path, raise_walk_error
from .models import DoctorCheck, DoctorPaths, DoctorReport, RepairAction, RepairKind, Severity


@dataclass(frozen=True)
class DirectoryEntry:
    relative: Path
    is_directory: bool
    sha256: str | None = None


@dataclass(frozen=True)
class CustomizationPair:
    name: str
    current: Path
    legacy: Path


def inspect_customization_layout(paths: DoctorPaths) -> DoctorReport:
    """Inspect active and previous customization directories."""
    report = DoctorReport()
    for pair in _pairs(paths):
        current_error = _directory_error(pair.current, label=f"Current {pair.name}")
        if current_error is not None:
            report.add_check(
                DoctorCheck("layout", f"{pair.name}_current", Severity.ERROR, current_error, pair.current),
            )
            continue

        legacy_error = _directory_error(pair.legacy, label=f"Legacy {pair.name}")
        if legacy_error is not None:
            report.add_check(
                DoctorCheck("layout", f"{pair.name}_legacy", Severity.ERROR, legacy_error, pair.legacy),
            )
            continue
        if not pair.legacy.exists():
            severity = Severity.PASS if pair.current.exists() else Severity.INFO
            message = (
                f"Current {pair.name} directory is ready."
                if pair.current.exists()
                else f"No {pair.name} customization directory is initialized."
            )
            report.add_check(DoctorCheck("layout", pair.name, severity, message, pair.current))
            continue

        try:
            _assert_migratable(pair)
        except OSError as exc:
            report.add_check(
                DoctorCheck("layout", f"{pair.name}_conflict", Severity.ERROR, str(exc), pair.legacy),
            )
            continue
        report.add_check(
            DoctorCheck(
                "layout",
                f"{pair.name}_legacy",
                Severity.REPAIRABLE,
                f"Legacy {pair.name} customizations can be migrated and archived.",
                pair.legacy,
            )
        )
        report.add_action(
            RepairAction(
                code=f"layout.migrate_{pair.name}",
                kind=RepairKind.LAYOUT,
                description=f"Migrate legacy {pair.name} customizations.",
                paths=(pair.legacy, pair.current),
            )
        )
    return report


def repair_customization_layout(paths: DoctorPaths, archive: DoctorArchive) -> list[DoctorCheck]:
    """Migrate each conflict-free legacy customization tree independently."""
    errors: list[DoctorCheck] = []
    for pair in _pairs(paths):
        if not pair.legacy.exists():
            continue
        try:
            entries = _assert_migratable(pair)
            _copy_missing(pair, entries)
            _assert_migratable(pair)
            archive.retire(pair.legacy, pair.legacy.relative_to(paths.root))
        except OSError as exc:
            errors.append(
                DoctorCheck(
                    "layout",
                    f"{pair.name}_repair_failed",
                    Severity.ERROR,
                    f"Could not migrate legacy {pair.name}: {exc}",
                    pair.legacy,
                )
            )
    return errors


def _pairs(paths: DoctorPaths) -> tuple[CustomizationPair, ...]:
    return (
        CustomizationPair("context", paths.context, paths.legacy_context),
        CustomizationPair("styles", paths.styles, paths.legacy_styles),
        CustomizationPair("prompts", paths.prompts, paths.legacy_prompts),
    )


def _directory_error(path: Path, *, label: str) -> str | None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{label} path could not be inspected: {exc}"
    if stat.S_ISLNK(mode):
        return f"{label} path is a symlink; repair is disabled."
    if not stat.S_ISDIR(mode):
        return f"{label} path is not a directory."
    return None


def _assert_migratable(pair: CustomizationPair) -> tuple[DirectoryEntry, ...]:
    legacy_error = _directory_error(pair.legacy, label=f"Legacy {pair.name}")
    if legacy_error is not None:
        raise OSError(legacy_error)
    current_error = _directory_error(pair.current, label=f"Current {pair.name}")
    if current_error is not None:
        raise OSError(current_error)

    entries = _inventory(pair.legacy)
    for entry in entries:
        destination = pair.current / entry.relative
        try:
            destination_mode = destination.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(destination_mode):
            msg = f"Destination is a symlink: {destination}"
            raise OSError(msg)
        if entry.is_directory:
            if not stat.S_ISDIR(destination_mode):
                msg = f"Directory conflicts with existing path: {destination}"
                raise OSError(msg)
        elif not stat.S_ISREG(destination_mode) or hash_path(destination) != entry.sha256:
            msg = f"File conflicts with current customization: {destination}"
            raise OSError(msg)
    return entries


def _inventory(root: Path) -> tuple[DirectoryEntry, ...]:
    entries: list[DirectoryEntry] = []
    for current, directories, files in os.walk(root, followlinks=False, onerror=raise_walk_error):
        directories.sort()
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                msg = f"Legacy customization contains a symlink: {path}"
                raise OSError(msg)
            entries.append(DirectoryEntry(relative=path.relative_to(root), is_directory=True))
        for name in sorted(files):
            path = current_path / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
                msg = f"Legacy customization contains an unsupported path: {path}"
                raise OSError(msg)
            entries.append(
                DirectoryEntry(
                    relative=path.relative_to(root),
                    is_directory=False,
                    sha256=hash_path(path),
                )
            )
    return tuple(entries)


def _copy_missing(pair: CustomizationPair, entries: tuple[DirectoryEntry, ...]) -> None:
    pair.current.mkdir(parents=True, exist_ok=True, mode=0o700)
    for entry in entries:
        source = pair.legacy / entry.relative
        destination = pair.current / entry.relative
        if entry.is_directory:
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            _atomic_copy_absent(source, destination)


def _atomic_copy_absent(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            source_descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                source_mode = os.fstat(source_descriptor).st_mode
                if not stat.S_ISREG(source_mode):
                    msg = f"Legacy customization is no longer a regular file: {source}"
                    raise OSError(msg)
                with os.fdopen(source_descriptor, "rb", closefd=False) as input_file:
                    shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
                os.fchmod(output.fileno(), stat.S_IMODE(source_mode))
            finally:
                os.close(source_descriptor)
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
