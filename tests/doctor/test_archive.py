"""Recovery archive behavior for doctor repairs."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from basecamp.doctor.archive import DoctorArchive
from basecamp.doctor.models import DoctorPaths


def test_backup_is_exact_private_and_manifested(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    source = paths.root / "config.json"
    paths.root.mkdir(parents=True)
    content = b'{"value": "exact"}\n'
    archive = DoctorArchive(paths, timestamp="20260719T120000000000Z")

    destination = archive.backup_bytes(source, content, Path("config.json"))

    assert destination.read_bytes() == content
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert archive.path is not None
    assert stat.S_IMODE(archive.path.stat().st_mode) == 0o700

    manifest_path = archive.path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert manifest["version"] == 1
    assert manifest["entries"] == [
        {
            "operation": "backup",
            "source": str(source),
            "destination": "backups/config.json",
            "sha256": "01f09a53e1338100e79f74f51a713aef7f38ada2c542e89ec1e226716d1e9c82",
        }
    ]


def test_retire_moves_verified_path_and_updates_manifest(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    source = paths.root / "workstream-launches"
    source.mkdir(parents=True)
    (source / "launch-index.json").write_text("{}\n", encoding="utf-8")
    archive = DoctorArchive(paths, timestamp="stamp")

    destination = archive.retire(source, Path("workstream-launches"))

    assert not source.exists()
    assert (destination / "launch-index.json").read_text(encoding="utf-8") == "{}\n"
    assert archive.path is not None
    manifest = json.loads((archive.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["entries"][0]["operation"] == "retire"
    assert manifest["entries"][0]["destination"] == "retired/workstream-launches"


def test_archive_rejects_escape_duplicate_and_symlink(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    archive = DoctorArchive(paths, timestamp="stamp")
    source = paths.root / "source"
    source.parent.mkdir(parents=True)
    source.write_text("data", encoding="utf-8")

    with pytest.raises(ValueError):
        archive.backup_bytes(source, b"data", Path("../escape"))

    archive.backup_bytes(source, b"data", Path("source"))
    with pytest.raises(FileExistsError):
        archive.backup_bytes(source, b"other", Path("source"))

    link = paths.root / "link"
    link.symlink_to(source)
    with pytest.raises(OSError):
        archive.retire(link, Path("link"))
    assert link.is_symlink()


def test_empty_failed_archive_is_removed_but_recovery_data_is_retained(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    paths.root.mkdir(parents=True)
    empty = DoctorArchive(paths, timestamp="empty")
    empty.reserve_backup_path(Path("swarm/daemon.db"))

    empty.discard_if_empty()

    assert empty.path is None
    assert not (paths.archive_root / "empty").exists()

    partial = DoctorArchive(paths, timestamp="partial")
    target = partial.reserve_backup_path(Path("swarm/daemon.db"))
    target.write_bytes(b"recoverable")

    partial.discard_if_empty()

    assert partial.path == paths.archive_root / "partial"
    assert partial.has_recovery_data is True
    assert target.read_bytes() == b"recoverable"


@pytest.mark.parametrize("component", ["backups", "doctor"])
def test_archive_prefix_symlink_is_never_followed(tmp_path: Path, component: str) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    external = tmp_path / "external"
    external.mkdir()
    paths.root.mkdir(parents=True)
    if component == "backups":
        paths.archive_root.parent.symlink_to(external, target_is_directory=True)
    else:
        paths.archive_root.parent.mkdir()
        paths.archive_root.symlink_to(external, target_is_directory=True)
    archive = DoctorArchive(paths, timestamp="stamp")

    with pytest.raises(OSError):
        archive.backup_bytes(paths.config, b"{}", Path("config.json"))

    assert list(external.iterdir()) == []


def test_timestamp_collision_uses_a_distinct_archive(tmp_path: Path) -> None:
    paths = DoctorPaths.for_home(tmp_path)
    existing = paths.archive_root / "stamp"
    existing.mkdir(parents=True)
    archive = DoctorArchive(paths, timestamp="stamp")

    archive.backup_bytes(paths.config, b"{}", Path("config.json"))

    assert archive.path == paths.archive_root / "stamp-1"
