from __future__ import annotations

import pytest

from basecamp.codex_sync.assets import PROJECTION, SKILLS
from basecamp.codex_sync.skills import (
    MANAGED_MARKER_BODY,
    MANAGED_MARKER_FILE,
    UnmanagedSkillConflictError,
    install_skills,
    preflight_skills,
)


def test_skills_are_declared_by_projection_manifest() -> None:
    declared_dirs = list(PROJECTION["skills"]["directories"])

    assert [entry["name"] for entry in declared_dirs] == [skill.name for skill in SKILLS]
    assert [entry["source"] for entry in declared_dirs] == [skill.source_ref for skill in SKILLS]
    assert {entry["install"] for entry in declared_dirs} == {"symlink"}
    for skill in SKILLS:
        assert (skill.source_dir / "SKILL.md").exists()


def test_skills_are_written_as_symlinks(tmp_path) -> None:
    result = install_skills(tmp_path)

    assert result.installed == 3
    assert result.updated == 0
    assert result.unchanged == 0

    for skill in SKILLS:
        path = tmp_path / skill.name
        assert path.is_symlink()
        assert path.resolve() == skill.source_dir.resolve()
        assert (path / "SKILL.md").exists()


def test_managed_skills_are_idempotent(tmp_path) -> None:
    install_skills(tmp_path)

    result = install_skills(tmp_path)

    assert result.installed == 0
    assert result.updated == 0
    assert result.unchanged == 3


def test_managed_copied_skill_is_migrated_to_symlink(tmp_path) -> None:
    path = tmp_path / SKILLS[0].name
    path.mkdir()
    (path / MANAGED_MARKER_FILE).write_text(MANAGED_MARKER_BODY)
    (path / "SKILL.md").write_text("---\nname: old\ndescription: old\n---\n")

    result = install_skills(tmp_path)

    assert result.installed == 2
    assert result.updated == 1
    assert result.unchanged == 0
    assert path.is_symlink()
    assert path.resolve() == SKILLS[0].source_dir.resolve()


def test_unmanaged_skill_conflict_fails_without_overwrite(tmp_path) -> None:
    path = tmp_path / SKILLS[0].name
    path.mkdir()
    original = "---\nname: custom\ndescription: custom\n---\n"
    (path / "SKILL.md").write_text(original)

    with pytest.raises(UnmanagedSkillConflictError):
        install_skills(tmp_path)

    assert (path / "SKILL.md").read_text() == original


def test_file_conflict_fails_without_overwrite(tmp_path) -> None:
    path = tmp_path / SKILLS[0].name
    original = "not a directory"
    path.write_text(original)

    with pytest.raises(UnmanagedSkillConflictError):
        install_skills(tmp_path)

    assert path.read_text() == original


def test_preflight_skills_detects_unmanaged_conflicts(tmp_path) -> None:
    path = tmp_path / SKILLS[0].name
    path.mkdir()
    (path / "SKILL.md").write_text("---\nname: custom\ndescription: custom\n---\n")

    with pytest.raises(UnmanagedSkillConflictError):
        preflight_skills(tmp_path)
