"""Tests for the observer CLI."""

from unittest.mock import patch

import observer.constants as c
import pytest
from click.testing import CliRunner
from observer.cli.observer import main


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def obs_dir(tmp_path, monkeypatch):
    """Redirect LOG constant for CLI tests."""
    obs = tmp_path / "observer"
    monkeypatch.setattr(c, "LOG_FILE", obs / "observer.log")
    return obs


class TestLogs:
    def test_missing_log_file(self, runner, obs_dir):  # noqa: ARG002
        result = runner.invoke(main, ["logs"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_exec_args(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("observer.cli.observer.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "-n", "50"])

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "tail"
        assert "-n50" in args[1]
        assert str(log_file) in args[1]

    def test_follow_flag(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("observer.cli.observer.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "--follow"])

        args = mock_exec.call_args[0]
        assert "-f" in args[1]


class TestSetup:
    def test_setup_initializes_db(self, runner, tmp_path, monkeypatch):
        monkeypatch.setattr(c, "BASECAMP_DIR", tmp_path)
        monkeypatch.setattr(c, "DB_PATH", tmp_path / "observer.db")
        monkeypatch.setattr(c, "DB_URL", f"sqlite:///{tmp_path / 'observer.db'}")
        monkeypatch.setattr(c, "CHROMA_DIR", tmp_path / "chroma")

        from observer.services.db import Database  # noqa: PLC0415

        monkeypatch.setattr(Database, "_instance", None)
        monkeypatch.setattr(Database, "_url", None)

        with patch("observer.cli.observer.questionary") as mock_q:
            import questionary  # noqa: PLC0415

            mock_q.select.return_value.ask.side_effect = ["sonnet", "haiku", "on"]
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"])

        assert result.exit_code == 0
        assert "configuration saved" in result.output.lower()
        Database.close_if_open()
