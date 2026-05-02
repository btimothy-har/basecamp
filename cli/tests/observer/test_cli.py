"""Tests for the observer CLI."""

from unittest.mock import patch

import basecamp.constants as bc
import pytest
from basecamp.cli.observer import main
from click.testing import CliRunner


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def obs_dir(tmp_path, monkeypatch):
    """Redirect LOG constant for CLI tests."""
    obs = tmp_path / "observer"
    monkeypatch.setattr(bc, "OBSERVER_LOG_FILE", obs / "observer.log")
    return obs


class TestLogs:
    def test_missing_log_file(self, runner, obs_dir):  # noqa: ARG002
        result = runner.invoke(main, ["logs"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_exec_args(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("basecamp.cli.observer.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "-n", "50"])

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "tail"
        assert "-n50" in args[1]
        assert str(log_file) in args[1]

    def test_follow_flag(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("basecamp.cli.observer.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "--follow"])

        args = mock_exec.call_args[0]
        assert "-f" in args[1]


class TestSetup:
    @pytest.fixture()
    def setup_env(self, tmp_path, monkeypatch):
        """Common setup for observer tests."""
        from basecamp.settings import Settings  # noqa: PLC0415

        db_url = f"sqlite:///{tmp_path / 'observer.db'}"
        test_settings = Settings(tmp_path / "config.json")

        monkeypatch.setattr(bc, "OBSERVER_DIR", tmp_path / "observer")
        monkeypatch.setattr(bc, "OBSERVER_DB_PATH", tmp_path / "observer.db")
        monkeypatch.setattr(bc, "OBSERVER_DB_URL", db_url)
        monkeypatch.setattr(bc, "OBSERVER_CHROMA_DIR", tmp_path / "chroma")
        monkeypatch.setattr("basecamp.cli.observer.settings", test_settings)

        # Patch the module-level bindings that db.py and chroma.py
        # captured at import time via `from ... import ...`.
        monkeypatch.setattr("observer.services.chroma.CHROMA_DIR", tmp_path / "chroma")

        from observer.services import chroma  # noqa: PLC0415

        chroma._state.clear()

        from observer.services.db import Database  # noqa: PLC0415

        monkeypatch.setattr(Database, "_instance", None)
        monkeypatch.setattr(Database, "_url", None)
        Database.configure(db_url)

        yield test_settings

        Database.close_if_open()

    def test_setup_initializes_db(self, runner, setup_env):  # noqa: ARG002
        result = runner.invoke(
            main,
            [
                "setup",
                "-e",
                "anthropic:claude-sonnet-4-20250514",
                "-s",
                "anthropic:claude-3-5-haiku-latest",
                "-m",
                "on",
            ],
        )

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()
        assert "anthropic:claude-sonnet-4-20250514" in result.output
        assert "anthropic:claude-3-5-haiku-latest" in result.output

    def test_setup_shows_provider_env_defaults(self, runner, setup_env):  # noqa: ARG002
        result = runner.invoke(main, ["setup"])

        assert result.exit_code == 0
        assert "Provider env var names" in result.output
        assert "OpenAI API key" in result.output
        assert "OPENAI_API_KEY" in result.output
        assert "Anthropic API key" in result.output
        assert "ANTHROPIC_API_KEY" in result.output

    def test_setup_openai_provider_flags(self, runner, setup_env):
        result = runner.invoke(
            main,
            [
                "setup",
                "--openai-api-key-env",
                "MY_OPENAI_KEY",
                "--openai-base-url-env",
                "MY_OPENAI_URL",
            ],
        )

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()
        assert "MY_OPENAI_KEY" in result.output
        assert "MY_OPENAI_URL" in result.output

        providers = setup_env.observer.provider_configs
        assert providers["openai"].api_key_env == "MY_OPENAI_KEY"
        assert providers["openai"].base_url_env == "MY_OPENAI_URL"

    def test_setup_anthropic_provider_flags(self, runner, setup_env):
        result = runner.invoke(
            main,
            [
                "setup",
                "--anthropic-api-key-env",
                "MY_ANTHROPIC_KEY",
                "--anthropic-base-url-env",
                "MY_ANTHROPIC_URL",
            ],
        )

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()
        assert "MY_ANTHROPIC_KEY" in result.output
        assert "MY_ANTHROPIC_URL" in result.output

        providers = setup_env.observer.provider_configs
        assert providers["anthropic"].api_key_env == "MY_ANTHROPIC_KEY"
        assert providers["anthropic"].base_url_env == "MY_ANTHROPIC_URL"

    def test_setup_provider_preserves_existing(self, runner, setup_env):
        from basecamp.settings import ProviderConfig  # noqa: PLC0415

        setup_env.observer.set_provider(
            "openai",
            ProviderConfig(api_key_env="EXISTING_KEY", base_url_env="EXISTING_URL"),
        )

        result = runner.invoke(
            main,
            [
                "setup",
                "--openai-api-key-env",
                "NEW_KEY",
            ],
        )

        assert result.exit_code == 0
        providers = setup_env.observer.provider_configs
        assert providers["openai"].api_key_env == "NEW_KEY"
        assert providers["openai"].base_url_env == "EXISTING_URL"

    def test_setup_provider_clear_with_empty_string(self, runner, setup_env):
        from basecamp.settings import ProviderConfig  # noqa: PLC0415

        setup_env.observer.set_provider(
            "openai",
            ProviderConfig(api_key_env="EXISTING_KEY", base_url_env="EXISTING_URL"),
        )

        result = runner.invoke(
            main,
            [
                "setup",
                "--openai-base-url-env",
                "",
            ],
        )

        assert result.exit_code == 0
        providers = setup_env.observer.provider_configs
        assert providers["openai"].api_key_env == "EXISTING_KEY"
        assert providers["openai"].base_url_env is None
