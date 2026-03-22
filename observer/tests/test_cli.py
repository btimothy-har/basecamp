"""Tests for the observer CLI."""

from unittest.mock import MagicMock, patch

import observer.constants as c
import pytest
import questionary
from click.testing import CliRunner
from observer.cli.observer import main
from observer.services.container import ContainerRuntimeNotFoundError, ContainerStatus


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def obs_dir(tmp_path, monkeypatch):
    """Redirect LOG constant and set env var for CLI tests."""
    obs = tmp_path / "observer"
    monkeypatch.setattr(c, "LOG_FILE", obs / "observer.log")
    monkeypatch.setenv("OBSERVER_PG_URL", "postgresql://localhost/observer_test")
    return obs


def _mock_status(*, running: bool = False, status_text: str = "running") -> ContainerStatus:
    return ContainerStatus(
        running=running,
        runtime="docker",
        container_name="observer-pg",
        port=15432,
        volume="observer_data",
        status_text=status_text,
    )


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
    PG_URL_WITH_CREDS = "postgresql://user:secret@host/db"

    def _mock_engine(self):
        """Return a mock engine whose connect() works as a context manager."""
        engine = MagicMock()
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = (1,)
        engine.connect.return_value = conn
        return engine

    def test_existing_url_masks_password(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch("observer.cli.observer.questionary") as mock_q,
            patch("observer.cli.observer.get_db_source", return_value="user"),
            patch("observer.cli.observer.get_pg_url", return_value=self.PG_URL_WITH_CREDS),
            patch("observer.cli.observer.create_engine", return_value=self._mock_engine()),
        ):
            mock_q.select.return_value.ask.side_effect = ["user", "sonnet", "haiku", "on"]
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"], input=f"{self.PG_URL_WITH_CREDS}\nn\n")

        current_url_line = next(line for line in result.output.splitlines() if line.startswith("Current URL:"))
        assert "***" in current_url_line
        assert "secret" not in current_url_line

    def test_container_source_creates_and_saves(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch("observer.cli.observer.questionary") as mock_q,
            patch("observer.cli.observer.detect_runtime", return_value="docker"),
            patch("observer.cli.observer.inspect_container", return_value=None),
            patch("observer.cli.observer.ensure_running", return_value=True),
            patch("observer.cli.observer.create_engine", return_value=self._mock_engine()),
            patch("observer.cli.observer.set_pg_url") as mock_set_url,
            patch("observer.cli.observer.set_db_source") as mock_set_source,
        ):
            mock_q.select.return_value.ask.side_effect = ["container", "sonnet", "haiku", "on"]
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"], input="n\n")

        assert result.exit_code == 0
        mock_set_source.assert_called_once_with("container")
        mock_set_url.assert_called_once()

    def test_no_runtime_exits(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch("observer.cli.observer.questionary") as mock_q,
            patch("observer.cli.observer.detect_runtime", side_effect=ContainerRuntimeNotFoundError),
        ):
            mock_q.select.return_value.ask.return_value = "container"
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"])

        assert result.exit_code != 0
        assert "docker" in result.output.lower() or "podman" in result.output.lower()
