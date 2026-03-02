"""Tests for the observer CLI."""

import json
from unittest.mock import MagicMock, patch

import observer.constants as c
import pytest
import questionary
from click.testing import CliRunner
from observer.cli import main
from observer.daemon import Daemon
from observer.services.container import ContainerRuntimeNotFoundError


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def obs_dir(tmp_path, monkeypatch):
    """Redirect PID/LOG constants and set env var for CLI tests."""
    obs = tmp_path / "observer"
    monkeypatch.setattr(c, "PID_FILE", obs / "observer.pid")
    monkeypatch.setattr(c, "LOG_FILE", obs / "observer.log")
    monkeypatch.setenv("OBSERVER_PG_URL", "postgresql://localhost/observer_test")
    return obs


class TestStart:
    def test_foreground(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=None), patch.object(Daemon, "run") as mock_run:
            result = runner.invoke(main, ["start", "--foreground"])

        assert result.exit_code == 0
        mock_run.assert_called_once_with(foreground=True)

    def test_already_running(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=12345):
            result = runner.invoke(main, ["start"])

        assert result.exit_code != 0
        assert "already running" in result.output

    def test_background(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=None), patch.object(Daemon, "run") as mock_run:
            result = runner.invoke(main, ["start"])

        assert result.exit_code == 0
        mock_run.assert_called_once_with(foreground=False)


class TestStop:
    def test_not_running(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=None):
            result = runner.invoke(main, ["stop"])

        assert result.exit_code != 0
        assert "not running" in result.output

    def test_success(self, runner, obs_dir):  # noqa: ARG002
        pid_file = obs_dir / "observer.pid"
        pid_file.write_text("99999")

        with (
            patch.object(Daemon, "check_running", return_value=99999),
            patch("observer.cli.os.kill") as mock_kill,
            patch.object(Daemon, "is_process_running", return_value=False),
        ):
            result = runner.invoke(main, ["stop"])

        assert result.exit_code == 0
        assert "stopped" in result.output.lower()
        mock_kill.assert_called_once()

    def test_timeout(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch.object(Daemon, "check_running", return_value=99999),
            patch("observer.cli.os.kill"),
            patch.object(Daemon, "is_process_running", return_value=True),
            patch("observer.cli.time.monotonic", side_effect=[0.0, 0.0, 100.0]),
            patch("observer.cli.time.sleep"),
        ):
            result = runner.invoke(main, ["stop", "--timeout", "1"])

        assert result.exit_code != 0
        assert "did not stop" in result.output


class TestStatus:
    def test_running(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=12345):
            result = runner.invoke(main, ["status"])

        assert result.exit_code == 0
        assert "12345" in result.output
        assert "running" in result.output.lower()

    def test_not_running(self, runner, obs_dir):  # noqa: ARG002
        with patch.object(Daemon, "check_running", return_value=None):
            result = runner.invoke(main, ["status"])

        assert result.exit_code == 3
        assert "not running" in result.output.lower()


class TestLogs:
    def test_missing_log_file(self, runner, obs_dir):  # noqa: ARG002
        result = runner.invoke(main, ["logs"])

        assert result.exit_code != 0
        assert "not found" in result.output.lower()

    def test_exec_args(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("observer.cli.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "-n", "50"])

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "tail"
        assert "-n50" in args[1]
        assert str(log_file) in args[1]

    def test_follow_flag(self, runner, obs_dir):  # noqa: ARG002
        log_file = obs_dir / "observer.log"
        log_file.write_text("test log line\n")

        with patch("observer.cli.os.execvp") as mock_exec:
            runner.invoke(main, ["logs", "--follow"])

        args = mock_exec.call_args[0]
        assert "-f" in args[1]


class TestRegister:
    def test_success(self, runner, obs_dir):  # noqa: ARG002
        stdin_json = json.dumps(
            {
                "session_id": "s1",
                "transcript_path": "/t.jsonl",
                "cwd": "/some/repo",
            }
        )
        mock_result = MagicMock(
            created=True,
            transcript=MagicMock(session_id="s1"),
        )
        with (
            patch("observer.services.registration.register_session", return_value=mock_result),
            patch("observer.services.registration.ensure_daemon_running", return_value=1234),
        ):
            result = runner.invoke(main, ["register"], input=stdin_json)

        assert result.exit_code == 0
        assert "Registered" in result.output

    def test_already_registered(self, runner, obs_dir):  # noqa: ARG002
        stdin_json = json.dumps(
            {
                "session_id": "s1",
                "transcript_path": "/t.jsonl",
                "cwd": "/some/repo",
            }
        )
        mock_result = MagicMock(
            created=False,
            transcript=MagicMock(session_id="s1"),
        )
        with (
            patch("observer.services.registration.register_session", return_value=mock_result),
            patch("observer.services.registration.ensure_daemon_running", return_value=1234),
        ):
            result = runner.invoke(main, ["register"], input=stdin_json)

        assert result.exit_code == 0
        assert "already registered" in result.output

    def test_empty_stdin(self, runner, obs_dir):  # noqa: ARG002
        result = runner.invoke(main, ["register"], input="")
        assert result.exit_code != 0
        assert "No input" in result.output

    def test_invalid_json(self, runner, obs_dir):  # noqa: ARG002
        result = runner.invoke(main, ["register"], input="not json")
        assert result.exit_code != 0
        assert "Invalid JSON" in result.output

    def test_not_a_repo(self, runner, obs_dir):  # noqa: ARG002
        stdin_json = json.dumps(
            {
                "session_id": "s1",
                "transcript_path": "/t.jsonl",
                "cwd": "/nonexistent",
            }
        )
        with patch(
            "observer.services.registration.register_session",
            side_effect=ValueError("Not a git repository: /nonexistent"),
        ):
            result = runner.invoke(main, ["register"], input=stdin_json)

        assert result.exit_code != 0
        assert "Not a git repository" in result.output


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
            patch("observer.cli.questionary") as mock_q,
            patch("observer.cli.get_db_source", return_value="user"),
            patch("observer.cli.get_pg_url", return_value=self.PG_URL_WITH_CREDS),
            patch("observer.cli.create_engine", return_value=self._mock_engine()),
        ):
            mock_q.select.return_value.ask.side_effect = ["user", "haiku", "haiku"]
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"], input=f"{self.PG_URL_WITH_CREDS}\nn\n")

        current_url_line = next(line for line in result.output.splitlines() if line.startswith("Current URL:"))
        assert "***" in current_url_line
        assert "secret" not in current_url_line

    def test_container_source_creates_and_saves(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch("observer.cli.questionary") as mock_q,
            patch("observer.cli.detect_runtime", return_value="docker"),
            patch("observer.cli.inspect_container", return_value=None),
            patch("observer.cli.start_container"),
            patch("observer.cli.wait_for_ready", return_value=True),
            patch("observer.cli.create_engine", return_value=self._mock_engine()),
            patch("observer.cli.set_pg_url") as mock_set_url,
            patch("observer.cli.set_db_source") as mock_set_source,
        ):
            mock_q.select.return_value.ask.side_effect = ["container", "haiku", "haiku"]
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"], input="n\n")

        assert result.exit_code == 0
        mock_set_source.assert_called_once_with("container")
        mock_set_url.assert_called_once()

    def test_no_runtime_exits(self, runner, obs_dir):  # noqa: ARG002
        with (
            patch("observer.cli.questionary") as mock_q,
            patch("observer.cli.detect_runtime", side_effect=ContainerRuntimeNotFoundError),
        ):
            mock_q.select.return_value.ask.return_value = "container"
            mock_q.Choice = questionary.Choice

            result = runner.invoke(main, ["setup"])

        assert result.exit_code != 0
        assert "docker" in result.output.lower() or "podman" in result.output.lower()
