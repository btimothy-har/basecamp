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
    def test_setup_initializes_db(self, runner, tmp_path, monkeypatch):
        db_url = f"sqlite:///{tmp_path / 'observer.db'}"

        monkeypatch.setattr(bc, "OBSERVER_DIR", tmp_path / "observer")
        monkeypatch.setattr(bc, "OBSERVER_DB_PATH", tmp_path / "observer.db")
        monkeypatch.setattr(bc, "OBSERVER_DB_URL", db_url)
        monkeypatch.setattr(bc, "OBSERVER_CHROMA_DIR", tmp_path / "chroma")

        # Patch the module-level bindings that db.py and chroma.py
        # captured at import time via `from ... import ...`.
        monkeypatch.setattr("observer.services.chroma.CHROMA_DIR", tmp_path / "chroma")

        from observer.services import chroma  # noqa: PLC0415

        chroma._state.clear()

        from observer.services.db import Database  # noqa: PLC0415

        monkeypatch.setattr(Database, "_instance", None)
        monkeypatch.setattr(Database, "_url", None)
        Database.configure(db_url)

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
        Database.close_if_open()
