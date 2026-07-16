"""Tests for basecamp.mcp.resolve — project-awareness resolution parity.

The resolution here must match the (retired) Pi extension's
``pi/core/project/config.ts`` exactly; these tests are the correctness surface.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from basecamp.core.settings import Settings
from basecamp.mcp.resolve import resolve_awareness, resolve_project


def _write_config(home: Path, projects: dict[str, Any]) -> Settings:
    config_path = home / ".pi" / "basecamp" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"projects": projects}))
    return Settings(config_path)


def test_projected_exact_match(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    extra = tmp_path / "shared"
    extra.mkdir()
    config = _write_config(
        tmp_path,
        {"myproj": {"repo_root": str(repo), "additional_dirs": [str(extra)], "context": None}},
    )
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.project_name == "myproj"
    assert result.projected
    assert result.related_dirs == [str(extra)]
    assert result.context_text is None
    assert not result.warnings


def test_unprojected_no_match(tmp_path: Path) -> None:
    config = _write_config(tmp_path, {"other": {"repo_root": str(tmp_path / "elsewhere")}})
    result = resolve_awareness(str(tmp_path / "repo"), home=tmp_path, config=config)
    assert result.project_name is None
    assert not result.projected
    assert result.related_dirs == []


def test_ambiguous_two_projects_same_root(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _write_config(tmp_path, {"a": {"repo_root": str(repo)}, "b": {"repo_root": str(repo)}})
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.project_name is None
    assert result.ambiguous
    assert result.warnings
    assert "ambiguous" in result.warnings[0].lower()


def test_not_a_repo_returns_unprojected(tmp_path: Path) -> None:
    result = resolve_awareness(None, home=tmp_path, config=_write_config(tmp_path, {}))
    assert result.project_name is None
    assert result.repo_root is None


@pytest.mark.parametrize("form", ["absolute", "tilde", "relative"])
def test_repo_root_path_forms_match(tmp_path: Path, form: str) -> None:
    repo = tmp_path / "code" / "repo"
    repo.mkdir(parents=True)
    configured = {"absolute": str(repo), "tilde": "~/code/repo", "relative": "code/repo"}[form]
    config = _write_config(tmp_path, {"p": {"repo_root": configured}})
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.project_name == "p"


def test_missing_additional_dir_dropped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    present = tmp_path / "present"
    present.mkdir()
    config = _write_config(
        tmp_path,
        {"p": {"repo_root": str(repo), "additional_dirs": [str(present), str(tmp_path / "ghost")]}},
    )
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.related_dirs == [str(present)]


def test_context_loaded_by_name(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    context_dir = tmp_path / ".pi" / "basecamp" / "context"
    context_dir.mkdir(parents=True)
    (context_dir / "notes.md").write_text("# House rules\nBe careful.")
    config = _write_config(tmp_path, {"p": {"repo_root": str(repo), "context": "notes"}})
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.context_text == "# House rules\nBe careful."


def test_context_name_missing_file_is_none(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = _write_config(tmp_path, {"p": {"repo_root": str(repo), "context": "absent"}})
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.project_name == "p"
    assert result.context_text is None


def test_invalid_config_degrades_gracefully(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    # additional_dirs as a non-list violates ProjectConfig -> LauncherError -> graceful degrade.
    config = _write_config(tmp_path, {"p": {"repo_root": str(repo), "additional_dirs": "nope"}})
    result = resolve_awareness(str(repo), home=tmp_path, config=config)
    assert result.project_name is None
    assert result.warnings


def test_resolve_project_outside_repo_is_unprojected(tmp_path: Path) -> None:
    # tmp_path is not a git repo -> git rev-parse fails -> unprojected.
    result = resolve_project(str(tmp_path), home=tmp_path, config=_write_config(tmp_path, {}))
    assert result.project_name is None
    assert result.repo_root is None


def test_resolve_project_in_repo(tmp_path: Path) -> None:
    # Use the realpath of tmp_path so git's symlink-resolved top-level matches the
    # abspath-only resolution (macOS /var -> /private/var).
    home = Path(os.path.realpath(tmp_path))
    repo = home / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    config = _write_config(home, {"p": {"repo_root": str(repo)}})
    result = resolve_project(str(repo), home=home, config=config)
    assert result.project_name == "p"
