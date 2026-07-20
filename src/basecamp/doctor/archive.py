"""Private, durable recovery archives for doctor repairs."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from basecamp.core.files import atomic_write_json

from .models import DoctorPaths


@dataclass(frozen=True)
class ArchiveEntry:
    """One backed-up or retired path recorded in the archive manifest."""

    operation: str
    source: str
    destination: str
    sha256: str


class DoctorArchive:
    """Lazily-created archive; every completed action updates its manifest."""

    def __init__(self, paths: DoctorPaths, *, timestamp: str | None = None) -> None:
        self._paths = paths
        self._timestamp = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        self._path: Path | None = None
        self._entries: list[ArchiveEntry] = []

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def has_entries(self) -> bool:
        return bool(self._entries)

    def backup_bytes(self, source: Path, content: bytes, relative: Path) -> Path:
        """Persist exact bytes under ``backups/`` and record their digest."""
        destination = self._destination("backups", relative)
        if destination.exists():
            msg = f"Archive destination already exists: {destination}"
            raise FileExistsError(msg)
        _atomic_write_bytes(destination, content)
        self._record("backup", source, destination, hashlib.sha256(content).hexdigest())
        return destination

    def reserve_backup_path(self, relative: Path) -> Path:
        """Reserve a private path for an external transactional backup writer."""
        destination = self._destination("backups", relative)
        if destination.exists():
            msg = f"Archive destination already exists: {destination}"
            raise FileExistsError(msg)
        return destination

    def record_backup(self, source: Path, destination: Path) -> None:
        """Record a backup written transactionally by another subsystem."""
        self._record("backup", source, destination, hash_path(destination))

    def retire(self, source: Path, relative: Path) -> Path:
        """Move a verified-redundant path under ``retired/`` without copying."""
        if source.is_symlink():
            msg = f"Refusing to archive symlink: {source}"
            raise OSError(msg)
        digest = hash_path(source)
        destination = self._destination("retired", relative)
        if destination.exists():
            msg = f"Archive destination already exists: {destination}"
            raise FileExistsError(msg)
        source.rename(destination)
        self._record("retire", source, destination, digest)
        return destination

    def _destination(self, category: str, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            msg = f"Archive path must be relative and contained: {relative}"
            raise ValueError(msg)
        root = self._ensure_root()
        destination = root / category / relative
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return destination

    def _ensure_root(self) -> Path:
        if self._path is not None:
            return self._path
        self._paths.archive_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        candidate = self._paths.archive_root / self._timestamp
        suffix = 1
        while candidate.exists():
            candidate = self._paths.archive_root / f"{self._timestamp}-{suffix}"
            suffix += 1
        candidate.mkdir(mode=0o700)
        self._path = candidate
        return candidate

    def _record(self, operation: str, source: Path, destination: Path, digest: str) -> None:
        root = self._ensure_root()
        self._entries.append(
            ArchiveEntry(
                operation=operation,
                source=str(source),
                destination=str(destination.relative_to(root)),
                sha256=digest,
            )
        )
        atomic_write_json(
            root / "manifest.json",
            {
                "version": 1,
                "created_at": self._timestamp,
                "entries": [asdict(entry) for entry in self._entries],
            },
            mode=0o600,
            dir_mode=0o700,
        )


def _atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as file:
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def hash_path(path: Path) -> str:
    mode = path.lstat().st_mode
    if stat.S_ISLNK(mode):
        msg = f"Refusing to hash symlink: {path}"
        raise OSError(msg)
    if stat.S_ISREG(mode):
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    if not stat.S_ISDIR(mode):
        msg = f"Unsupported archive path type: {path}"
        raise OSError(msg)

    digest = hashlib.sha256()
    for root, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        root_path = Path(root)
        for name in sorted([*directories, *files]):
            item = root_path / name
            if item.is_symlink():
                msg = f"Refusing to hash directory containing symlink: {item}"
                raise OSError(msg)
            relative = item.relative_to(path)
            digest.update(relative.as_posix().encode())
            if item.is_file():
                digest.update(hash_path(item).encode())
    return digest.hexdigest()
