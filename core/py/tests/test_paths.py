"""Tests for basecamp_core.paths and public API surface."""

from __future__ import annotations

from pathlib import Path

import basecamp_core
from basecamp_core import paths


class TestPaths:
    def test_pi_dir_under_home(self) -> None:
        assert paths.PI_DIR == Path.home() / ".pi"

    def test_basecamp_config_dir_under_pi_dir(self) -> None:
        assert paths.BASECAMP_CONFIG_DIR == paths.PI_DIR / "basecamp"

    def test_default_config_path_under_basecamp_config_dir(self) -> None:
        assert paths.DEFAULT_CONFIG_PATH == paths.BASECAMP_CONFIG_DIR / "config.json"

    def test_workspace_dir_under_basecamp_config_dir(self) -> None:
        assert paths.BASECAMP_WORKSPACE_DIR == paths.BASECAMP_CONFIG_DIR / "workspace"

    def test_user_dirs_under_basecamp_workspace_dir(self) -> None:
        assert paths.USER_CONTEXT_DIR == paths.BASECAMP_WORKSPACE_DIR / "context"
        assert paths.USER_STYLES_DIR == paths.BASECAMP_WORKSPACE_DIR / "styles"
        assert paths.USER_PROMPTS_DIR == paths.BASECAMP_WORKSPACE_DIR / "prompts"


class TestPublicApi:
    def test_exports_present(self) -> None:
        expected = {
            "BASECAMP_CONFIG_DIR",
            "BASECAMP_WORKSPACE_DIR",
            "DEFAULT_CONFIG_PATH",
            "LauncherError",
            "PI_DIR",
            "Settings",
            "USER_CONTEXT_DIR",
            "USER_PROMPTS_DIR",
            "USER_STYLES_DIR",
            "atomic_write_json",
            "settings",
        }
        assert expected <= set(basecamp_core.__all__)
        for name in expected:
            assert hasattr(basecamp_core, name)

    def test_launcher_error_is_exception(self) -> None:
        assert issubclass(basecamp_core.LauncherError, Exception)
