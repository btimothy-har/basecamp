"""Compatibility tests for basecamp-cli wrappers during package split."""

from __future__ import annotations

from pathlib import Path

from basecamp_cli.config import ProjectConfig, load_projects, save_projects
from basecamp_cli.settings import Settings
from basecamp_workspace.projects import ProjectConfig as WorkspaceProjectConfig


def test_project_config_reexport() -> None:
    """basecamp_cli.config keeps exporting the workspace project model."""
    assert ProjectConfig is WorkspaceProjectConfig


def test_settings_projects_compatibility_property(tmp_path: Path) -> None:
    """basecamp_cli.settings.Settings keeps project accessors temporarily."""
    cfg = Settings(tmp_path / "config.json")

    cfg.projects = {"demo": {"dirs": ["src/demo", "src/shared"]}}

    assert cfg.projects == {
        "demo": {
            "repo_root": "src/demo",
            "additional_dirs": ["src/shared"],
        }
    }


def test_project_function_reexports_are_callable() -> None:
    """Existing imports still expose project load/save functions."""
    assert callable(load_projects)
    assert callable(save_projects)
