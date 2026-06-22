"""Codex skill installation."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from basecamp.codex_sync.assets import SKILLS, SkillDefinition

MANAGED_MARKER_BODY = "Managed by basecamp codex sync; source=basecamp.codex_sync skills v1"
MANAGED_MARKER_FILE = ".basecamp-codex-sync"


class CodexSkillError(Exception):
    """Raised when Codex skills cannot be safely installed."""


class UnmanagedSkillConflictError(CodexSkillError):
    """Raised when an unmanaged same-name skill directory exists."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"Refusing to overwrite unmanaged Codex skill directory: {path}")


@dataclass(frozen=True)
class SkillInstallResult:
    """Summary of installed Codex skills."""

    installed: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.installed + self.updated + self.unchanged


def preflight_skills(skills_dir: Path) -> None:
    """Validate existing skill directories before mutating Codex config."""
    for skill in SKILLS:
        path = skills_dir / skill.name
        if _path_exists(path) and not _is_managed_skill(path, skill):
            raise UnmanagedSkillConflictError(path)


def install_skills(skills_dir: Path) -> SkillInstallResult:
    """Install managed Codex skill directories."""
    installed = 0
    updated = 0
    unchanged = 0

    for skill in SKILLS:
        path = skills_dir / skill.name
        was_installed = not _path_exists(path)
        changed = _install_skill(skills_dir, skill)

        if not changed:
            unchanged += 1
        elif was_installed:
            installed += 1
        else:
            updated += 1

    return SkillInstallResult(installed=installed, updated=updated, unchanged=unchanged)


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _is_managed_skill(path: Path, skill: SkillDefinition) -> bool:
    if skill.install_mode == "symlink" and _is_expected_symlink(path, skill):
        return True
    return _is_managed_copy(path)


def _is_expected_symlink(path: Path, skill: SkillDefinition) -> bool:
    if not path.is_symlink():
        return False
    try:
        return path.resolve(strict=True) == skill.source_dir.resolve(strict=True)
    except OSError:
        return False


def _is_managed_copy(path: Path) -> bool:
    if path.is_symlink() or not path.is_dir():
        return False
    marker = path / MANAGED_MARKER_FILE
    try:
        return marker.read_text() == MANAGED_MARKER_BODY
    except OSError:
        return False


def _file_map(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        files[file_path.relative_to(path).as_posix()] = file_path.read_bytes()
    return files


def _stage_skill(parent: Path, skill: SkillDefinition) -> Path:
    staged = parent / skill.name
    shutil.copytree(skill.source_dir, staged)
    (staged / MANAGED_MARKER_FILE).write_text(MANAGED_MARKER_BODY)
    return staged


def _remove_existing(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    shutil.rmtree(path)


def _install_skill(skills_dir: Path, skill: SkillDefinition) -> bool:
    target = skills_dir / skill.name
    if _path_exists(target) and not _is_managed_skill(target, skill):
        raise UnmanagedSkillConflictError(target)

    if skill.install_mode == "symlink":
        if _is_expected_symlink(target, skill):
            return False
        if _path_exists(target):
            _remove_existing(target)
        target.symlink_to(skill.source_dir, target_is_directory=True)
        return True

    with tempfile.TemporaryDirectory(prefix=f".{skill.name}.", dir=skills_dir) as tmp:
        staged = _stage_skill(Path(tmp), skill)
        if _path_exists(target) and _file_map(target) == _file_map(staged):
            return False

        if _path_exists(target):
            _remove_existing(target)
        staged.rename(target)
        return True
