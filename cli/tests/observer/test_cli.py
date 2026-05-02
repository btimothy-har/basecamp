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

    def test_setup_initializes_db(self, runner, setup_env):
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
        assert setup_env.observer.extraction_model == "anthropic:claude-sonnet-4-20250514"
        assert setup_env.observer.summary_model == "anthropic:claude-3-5-haiku-latest"

    @pytest.mark.usefixtures("setup_env")
    def test_setup_rejects_bare_model_ref(self, runner):
        result = runner.invoke(main, ["setup", "--summary-model", "gpt-4o-mini"])

        assert result.exit_code != 0
        assert "provider:model_id" in result.output

    def test_setup_accepts_explicit_alias_target(self, runner, setup_env):
        setup_env.models = {"fast": "openai:gpt-4o-mini"}

        result = runner.invoke(main, ["setup", "--summary-model", "fast"])

        assert result.exit_code == 0
        assert setup_env.observer.summary_model == "fast"

    @pytest.mark.usefixtures("setup_env")
    def test_setup_shows_provider_env_defaults(self, runner):
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

    def test_setup_provider_clear_api_key_with_empty_string(self, runner, setup_env):
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
                "",
            ],
        )

        assert result.exit_code == 0
        providers = setup_env.observer.provider_configs
        assert providers["openai"].api_key_env is None
        assert providers["openai"].base_url_env == "EXISTING_URL"

    @pytest.mark.usefixtures("setup_env")
    def test_setup_shows_openrouter_provider_defaults(self, runner):
        result = runner.invoke(main, ["setup"])

        assert result.exit_code == 0
        assert "OpenRouter API key" in result.output
        assert "OPENROUTER_API_KEY" in result.output
        assert "OpenRouter base URL" in result.output
        assert "OPENROUTER_BASE_URL" in result.output

    def test_setup_openrouter_provider_flags(self, runner, setup_env):
        result = runner.invoke(
            main,
            [
                "setup",
                "--openrouter-api-key-env",
                "MY_OPENROUTER_KEY",
                "--openrouter-base-url-env",
                "MY_OPENROUTER_URL",
            ],
        )

        assert result.exit_code == 0
        assert "configuration updated" in result.output.lower()
        assert "MY_OPENROUTER_KEY" in result.output
        assert "MY_OPENROUTER_URL" in result.output

        providers = setup_env.observer.provider_configs
        assert providers["openrouter"].api_key_env == "MY_OPENROUTER_KEY"
        assert providers["openrouter"].base_url_env == "MY_OPENROUTER_URL"

    def test_setup_openrouter_preserves_existing(self, runner, setup_env):
        from basecamp.settings import ProviderConfig  # noqa: PLC0415

        setup_env.observer.set_provider(
            "openrouter",
            ProviderConfig(api_key_env="EXISTING_KEY", base_url_env="EXISTING_URL"),
        )

        result = runner.invoke(
            main,
            [
                "setup",
                "--openrouter-api-key-env",
                "NEW_KEY",
            ],
        )

        assert result.exit_code == 0
        providers = setup_env.observer.provider_configs
        assert providers["openrouter"].api_key_env == "NEW_KEY"
        assert providers["openrouter"].base_url_env == "EXISTING_URL"

    def test_setup_openrouter_clear_with_empty_string(self, runner, setup_env):
        from basecamp.settings import ProviderConfig  # noqa: PLC0415

        setup_env.observer.set_provider(
            "openrouter",
            ProviderConfig(api_key_env="EXISTING_KEY", base_url_env="EXISTING_URL"),
        )

        result = runner.invoke(
            main,
            [
                "setup",
                "--openrouter-base-url-env",
                "",
            ],
        )

        assert result.exit_code == 0
        providers = setup_env.observer.provider_configs
        assert providers["openrouter"].api_key_env == "EXISTING_KEY"
        assert providers["openrouter"].base_url_env is None


class TestSetupHelpText:
    def test_setup_help_uses_explicit_provider_syntax(self, runner):
        """Help text should not advertise bare model refs or old syntax."""
        result = runner.invoke(main, ["setup", "--help"])

        assert result.exit_code == 0
        assert "provider:model_id" in result.output
        assert "Supported providers: openai, anthropic, openrouter" in result.output
        assert "OpenAI Responses" in result.output

        assert "[provider:]" not in result.output
        assert "Provider defaults to" not in result.output
        assert "openai-chat:" not in result.output
        assert "openai-responses:" not in result.output
