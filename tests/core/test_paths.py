"""Tests for basecamp.core.paths and public API surface."""

from __future__ import annotations

from pathlib import Path

import basecamp.core
from basecamp.core import paths
from basecamp.core.settings import Settings, settings


class TestPaths:
    def test_pi_dir_under_home(self) -> None:
        assert paths.PI_DIR == Path.home() / ".pi"

    def test_basecamp_config_dir_under_pi_dir(self) -> None:
        assert paths.BASECAMP_CONFIG_DIR == paths.PI_DIR / "basecamp"

    def test_default_config_path_under_basecamp_config_dir(self) -> None:
        assert paths.DEFAULT_CONFIG_PATH == paths.BASECAMP_CONFIG_DIR / "config.json"

    def test_user_dirs_under_basecamp_config_dir(self) -> None:
        assert paths.USER_CONTEXT_DIR == paths.BASECAMP_CONFIG_DIR / "context"
        assert paths.USER_STYLES_DIR == paths.BASECAMP_CONFIG_DIR / "styles"
        assert paths.USER_PROMPTS_DIR == paths.BASECAMP_CONFIG_DIR / "prompts"


class TestPublicApi:
    def test_exports_present(self) -> None:
        # NB: the ``settings`` singleton is intentionally not re-exported here —
        # its name collides with the ``basecamp.core.settings`` subpackage, so
        # binding it on ``basecamp.core`` would shadow the package for
        # ``import basecamp.core.settings.<sub>`` forms. Import it from its module:
        # ``from basecamp.core.settings import settings``.
        expected = {
            "BASECAMP_CONFIG_DIR",
            "DEFAULT_CONFIG_PATH",
            "LauncherError",
            "PI_DIR",
            "Settings",
            "USER_CONTEXT_DIR",
            "USER_PROMPTS_DIR",
            "USER_STYLES_DIR",
            "atomic_write_json",
        }
        assert expected <= set(basecamp.core.__all__)
        for name in expected:
            assert hasattr(basecamp.core, name)

    def test_settings_singleton_importable_from_module(self) -> None:
        assert isinstance(settings, Settings)

    def test_launcher_error_is_exception(self) -> None:
        assert issubclass(basecamp.core.LauncherError, Exception)
