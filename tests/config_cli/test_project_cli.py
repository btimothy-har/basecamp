"""Tests for the `basecamp config project` CLI helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from basecamp.config_cli import project as project_cli
from basecamp.core.settings import Settings


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_available_styles_uses_runtime_prompt_style_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_dir = tmp_path / "install"
    builtin_styles = install_dir / "pi" / "system-prompt" / "defaults" / "styles"
    stale_styles = install_dir / "pi" / "workspace" / "prompt" / "system-prompts" / "styles"
    user_styles = tmp_path / "user-styles"
    _write(builtin_styles / "engineering.md")
    _write(stale_styles / "stale.md")
    _write(user_styles / "custom.md")

    settings = Settings(tmp_path / "config.json")
    settings.install_dir = str(install_dir)
    monkeypatch.setattr(project_cli, "settings", settings)
    monkeypatch.setattr(project_cli, "USER_STYLES_DIR", user_styles)

    assert project_cli._available_styles() == ["custom", "engineering"]
