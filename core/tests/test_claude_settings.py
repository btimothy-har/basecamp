"""Tests for core.config.claude_settings."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from core.config.claude_settings import _load_user_settings, build_session_settings


@pytest.fixture
def paths(tmp_path: Path) -> dict[str, Path]:
    """Patch all module-level path constants to tmp_path subdirs.

    Yields a dict with keys: cache, scratch, tasks, user_settings.
    """
    cache = tmp_path / "cache"
    scratch = tmp_path / "scratch"
    tasks = tmp_path / "tasks"
    user_settings = tmp_path / "user_settings.json"
    with (
        patch("core.config.claude_settings.CACHE_DIR", cache),
        patch("core.config.claude_settings.SCRATCH_BASE", scratch),
        patch("core.config.claude_settings._WORKERS_DIR", tasks),
        patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", user_settings),
    ):
        yield {
            "cache": cache,
            "scratch": scratch,
            "tasks": tasks,
            "user_settings": user_settings,
        }


def _make_dotenv(tmp_path: Path, content: str = "") -> Path:
    """Write a .env file and return its path."""
    dotenv = tmp_path / ".env"
    dotenv.write_text(content)
    return dotenv


def _read_output(path: Path) -> dict:
    return json.loads(path.read_text())


class TestLoadUserSettings:
    """Tests for _load_user_settings()."""

    def test_valid_json_returns_dict(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"theme": "dark", "apiKeyHelper": "/helper"}))
        with patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", settings_path):
            result = _load_user_settings()
        assert result == {"theme": "dark", "apiKeyHelper": "/helper"}

    def test_missing_file_returns_empty_dict(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", missing):
            result = _load_user_settings()
        assert result == {}

    def test_corrupt_json_returns_empty_dict(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("{invalid json")
        with patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", settings_path):
            result = _load_user_settings()
        assert result == {}

    def test_non_dict_list_returns_empty_dict(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text("[1, 2, 3]")
        with patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", settings_path):
            result = _load_user_settings()
        assert result == {}

    def test_non_dict_string_returns_empty_dict(self, tmp_path: Path) -> None:
        settings_path = tmp_path / "settings.json"
        settings_path.write_text('"just a string"')
        with patch("core.config.claude_settings.CLAUDE_USER_SETTINGS", settings_path):
            result = _load_user_settings()
        assert result == {}


@pytest.mark.usefixtures("paths")
class TestBuildSessionSettings:
    """Tests for build_session_settings()."""

    # --- apiKeyHelper ---

    def test_api_key_helper_stripped(self, paths: dict, tmp_path: Path) -> None:
        paths["user_settings"].write_text(json.dumps({"apiKeyHelper": "/bin/helper", "theme": "dark"}))
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert "apiKeyHelper" not in result
        assert result.get("theme") == "dark"

    # --- .env vars ---

    def test_dotenv_vars_in_settings_env(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path, "MY_KEY=my_value\nANOTHER=123\n")

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert result["env"]["MY_KEY"] == "my_value"
        assert result["env"]["ANOTHER"] == "123"

    def test_user_settings_env_present_in_output(self, paths: dict, tmp_path: Path) -> None:
        paths["user_settings"].write_text(json.dumps({"env": {"USER_VAR": "user_value"}}))
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert result["env"]["USER_VAR"] == "user_value"

    def test_dotenv_wins_over_user_settings_env(self, paths: dict, tmp_path: Path) -> None:
        """When both .env and user settings.env define the same key, .env wins."""
        paths["user_settings"].write_text(json.dumps({"env": {"SHARED_KEY": "user_value"}}))
        dotenv = _make_dotenv(tmp_path, "SHARED_KEY=dotenv_value\n")

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert result["env"]["SHARED_KEY"] == "dotenv_value"

    def test_empty_dotenv_file(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert isinstance(result["env"], dict)

    def test_missing_dotenv_file(self, tmp_path: Path) -> None:
        dotenv = tmp_path / "nonexistent.env"

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert isinstance(result["env"], dict)

    # --- permissions ---

    def test_scratch_dir_permissions(self, paths: dict, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        scratch_dir = paths["scratch"] / "myproject"
        allow = result["permissions"]["allow"]
        for tool in ("Read", "Write", "Edit"):
            assert f"{tool}({scratch_dir}/**)" in allow

    def test_tasks_dir_permissions(self, paths: dict, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        tasks_dir = paths["tasks"]
        allow = result["permissions"]["allow"]
        for tool in ("Read", "Write", "Edit"):
            assert f"{tool}({tasks_dir}/**)" in allow

    def test_existing_user_permissions_preserved(self, paths: dict, tmp_path: Path) -> None:
        paths["user_settings"].write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]}}))
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert "Bash(ls)" in result["permissions"]["allow"]

    # --- BASECAMP_* env vars ---

    def test_basecamp_core_env_vars_present(self, paths: dict, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        env = result["env"]
        assert env["BASECAMP_PROJECT"] == "myproject"
        assert env["BASECAMP_REPO"] == "myrepo"
        assert env["BASECAMP_SCRATCH_DIR"] == str(paths["scratch"] / "myproject")
        assert env["BASECAMP_SETTINGS_FILE"] == str(out)

    def test_system_prompt_path_sets_env_var(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
            system_prompt_path="/tmp/prompt.md",
        )
        result = _read_output(out)
        assert result["env"]["BASECAMP_SYSTEM_PROMPT"] == "/tmp/prompt.md"

    def test_no_system_prompt_path_absent_from_env(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = _read_output(out)
        assert "BASECAMP_SYSTEM_PROMPT" not in result["env"]

    def test_context_file_path_sets_env_var(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
            context_file_path="/tmp/context.md",
        )
        result = _read_output(out)
        assert result["env"]["BASECAMP_CONTEXT_FILE"] == "/tmp/context.md"

    def test_observer_enabled_sets_env_var(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
            observer_enabled=True,
        )
        result = _read_output(out)
        assert result["env"]["BASECAMP_OBSERVER_ENABLED"] == "1"

    def test_observer_disabled_absent_from_env(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
            observer_enabled=False,
        )
        result = _read_output(out)
        assert "BASECAMP_OBSERVER_ENABLED" not in result["env"]

    # --- Output path ---

    def test_label_produces_subdirectory_path(self, paths: dict, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
            label="auth",
        )
        assert out == paths["cache"] / "myproject" / "auth" / "settings.json"

    def test_no_label_produces_flat_path(self, paths: dict, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        assert out == paths["cache"] / "myproject" / "settings.json"

    # --- File properties ---

    def test_output_file_mode_is_0o600(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        assert out.stat().st_mode & 0o777 == 0o600

    def test_output_is_valid_json_dict(self, tmp_path: Path) -> None:
        dotenv = _make_dotenv(tmp_path)

        out = build_session_settings(
            project_name="myproject",
            repo_name="myrepo",
            scratch_name="myproject",
            dotenv_path=dotenv,
        )
        result = json.loads(out.read_text())
        assert isinstance(result, dict)
