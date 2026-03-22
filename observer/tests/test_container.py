"""Tests for container runtime management and db CLI commands."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from observer.cli.observer import main
from observer.services.container import (
    ContainerRuntimeNotFoundError,
    ContainerStatus,
    detect_runtime,
    ensure_running,
    inspect_container,
    remove_volume,
    volume_exists,
)


@pytest.fixture()
def runner():
    return CliRunner()


class TestDetectRuntime:
    def test_docker_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker" if name == "docker" else None)
        assert detect_runtime() == "docker"

    def test_podman_fallback(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/podman" if name == "podman" else None)
        assert detect_runtime() == "podman"

    def test_neither_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(ContainerRuntimeNotFoundError):
            detect_runtime()


class TestInspectContainer:
    def test_container_running(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="running\n", stderr="")
        with patch("observer.services.container._run", return_value=fake):
            status = inspect_container("docker")

        assert status is not None
        assert status.running is True
        assert status.status_text == "running"

    def test_container_exited(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="exited\n", stderr="")
        with patch("observer.services.container._run", return_value=fake):
            status = inspect_container("docker")

        assert status is not None
        assert status.running is False
        assert status.status_text == "exited"

    def test_container_missing(self):
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="No such object")
        with patch("observer.services.container._run", return_value=fake):
            status = inspect_container("docker")

        assert status is None


_CLI_PREFIX = "observer.cli.observer"


def _mock_status(*, running: bool = False, status_text: str = "running") -> ContainerStatus:
    return ContainerStatus(
        running=running,
        runtime="docker",
        container_name="observer-pg",
        port=15432,
        volume="observer_data",
        status_text=status_text,
    )


class TestDbUp:
    def test_not_configured_exits(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value=None):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code != 0
        assert "observer setup" in result.output.lower()

    def test_user_source_exits(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value="user"):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code != 0
        assert "externally managed" in result.output.lower()

    def test_no_runtime(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", side_effect=ContainerRuntimeNotFoundError),
        ):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code != 0
        assert "docker" in result.output.lower() or "podman" in result.output.lower()

    def test_already_running(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=True)),
            patch(f"{_CLI_PREFIX}.ensure_running", return_value=True),
        ):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code == 0
        assert "checking" in result.output.lower()
        assert "ready" in result.output.lower()

    def test_new_container(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=None),
            patch(f"{_CLI_PREFIX}.ensure_running", return_value=True) as mock_ensure,
        ):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code == 0
        assert "creating" in result.output.lower()
        assert "ready" in result.output.lower()
        mock_ensure.assert_called_once_with("docker")

    def test_restart_stopped(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=False, status_text="exited")),
            patch(f"{_CLI_PREFIX}.ensure_running", return_value=True),
        ):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code == 0
        assert "restarting" in result.output.lower()

    def test_ready_timeout(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=None),
            patch(f"{_CLI_PREFIX}.ensure_running", return_value=False),
            patch(f"{_CLI_PREFIX}.container_logs", return_value="pg startup failed"),
        ):
            result = runner.invoke(main, ["db", "up"])

        assert result.exit_code != 0
        assert "timed out" in result.output.lower()


class TestDbDown:
    def test_not_configured_exits(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value=None):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code != 0
        assert "observer setup" in result.output.lower()

    def test_user_source_exits(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value="user"):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code != 0
        assert "externally managed" in result.output.lower()

    def test_no_runtime(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", side_effect=ContainerRuntimeNotFoundError),
        ):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code != 0

    def test_not_found(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=None),
        ):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_running_stop_and_remove(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=True)),
            patch(f"{_CLI_PREFIX}.stop_container") as mock_stop,
            patch(f"{_CLI_PREFIX}.remove_container") as mock_rm,
        ):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code == 0
        assert "removed" in result.output.lower()
        mock_stop.assert_called_once_with("docker")
        mock_rm.assert_called_once_with("docker")

    def test_stopped_remove_only(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=False, status_text="exited")),
            patch(f"{_CLI_PREFIX}.stop_container") as mock_stop,
            patch(f"{_CLI_PREFIX}.remove_container") as mock_rm,
        ):
            result = runner.invoke(main, ["db", "down"])

        assert result.exit_code == 0
        mock_stop.assert_not_called()
        mock_rm.assert_called_once_with("docker")


class TestDbStatus:
    def test_not_configured(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value=None):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "not configured" in result.output.lower()

    def test_user_source_shows_url(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="user"),
            patch(f"{_CLI_PREFIX}.get_pg_url", return_value="postgresql://u:p@host/db"),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "user" in result.output.lower()
        assert "***" in result.output

    def test_container_running(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.get_pg_url", return_value="postgresql://localhost:15432/observer"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=True)),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "container" in result.output.lower()
        assert "running" in result.output.lower()

    def test_container_not_found(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.get_pg_url", return_value="postgresql://localhost:15432/observer"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=None),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "not found" in result.output.lower()

    def test_container_stopped(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.get_pg_url", return_value="postgresql://localhost:15432/observer"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container", return_value=_mock_status(running=False, status_text="exited")),
        ):
            result = runner.invoke(main, ["db", "status"])

        assert result.exit_code == 0
        assert "exited" in result.output.lower()


class TestDbReset:
    def test_happy_path(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", return_value="docker"),
            patch(f"{_CLI_PREFIX}.inspect_container") as mock_inspect,
            patch(f"{_CLI_PREFIX}.stop_container") as mock_stop,
            patch(f"{_CLI_PREFIX}.remove_container") as mock_rm,
            patch(f"{_CLI_PREFIX}.volume_exists", return_value=True),
            patch(f"{_CLI_PREFIX}.remove_volume") as mock_rm_vol,
            patch(f"{_CLI_PREFIX}.ensure_running", return_value=True) as mock_ensure,
            patch(f"{_CLI_PREFIX}.container_logs", return_value=""),
        ):
            # First call (teardown) returns running; second call (recreate) returns None
            mock_inspect.side_effect = [_mock_status(running=True), None]
            result = runner.invoke(main, ["db", "reset", "--yes"])

        assert result.exit_code == 0
        assert "reset" in result.output.lower()
        mock_stop.assert_called_once()
        mock_rm.assert_called_once()
        mock_rm_vol.assert_called_once()
        mock_ensure.assert_called_once()

    def test_declined(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"):
            result = runner.invoke(main, ["db", "reset"], input="n\n")

        assert result.exit_code == 0
        assert "aborted" in result.output.lower()

    def test_user_source_exits(self, runner):
        with patch(f"{_CLI_PREFIX}.get_db_source", return_value="user"):
            result = runner.invoke(main, ["db", "reset", "--yes"])

        assert result.exit_code != 0
        assert "externally managed" in result.output.lower()

    def test_no_runtime(self, runner):
        with (
            patch(f"{_CLI_PREFIX}.get_db_source", return_value="container"),
            patch(f"{_CLI_PREFIX}.detect_runtime", side_effect=ContainerRuntimeNotFoundError),
        ):
            result = runner.invoke(main, ["db", "reset", "--yes"])

        assert result.exit_code != 0


_SVC_PREFIX = "observer.services.container"


class TestEnsureRunning:
    def test_already_running_still_checks_readiness(self):
        with (
            patch(f"{_SVC_PREFIX}.inspect_container", return_value=_mock_status(running=True)),
            patch(f"{_SVC_PREFIX}.wait_for_ready", return_value=True) as mock_wait,
        ):
            assert ensure_running("docker") is True
            mock_wait.assert_called_once_with("docker")

    def test_stopped_restarts(self):
        with (
            patch(f"{_SVC_PREFIX}.inspect_container", return_value=_mock_status(running=False, status_text="exited")),
            patch(f"{_SVC_PREFIX}.restart_container") as mock_restart,
            patch(f"{_SVC_PREFIX}.wait_for_ready", return_value=True),
        ):
            assert ensure_running("docker") is True
            mock_restart.assert_called_once_with("docker")

    def test_missing_creates(self):
        with (
            patch(f"{_SVC_PREFIX}.inspect_container", return_value=None),
            patch(f"{_SVC_PREFIX}.start_container") as mock_start,
            patch(f"{_SVC_PREFIX}.wait_for_ready", return_value=True),
        ):
            assert ensure_running("docker") is True
            mock_start.assert_called_once_with("docker")

    def test_timeout_returns_false(self):
        with (
            patch(f"{_SVC_PREFIX}.inspect_container", return_value=None),
            patch(f"{_SVC_PREFIX}.start_container"),
            patch(f"{_SVC_PREFIX}.wait_for_ready", return_value=False),
        ):
            assert ensure_running("docker") is False


class TestVolumeOps:
    def test_volume_exists_true(self):
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        with patch(f"{_SVC_PREFIX}._run", return_value=fake):
            assert volume_exists("docker") is True

    def test_volume_exists_false(self):
        fake = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="")
        with patch(f"{_SVC_PREFIX}._run", return_value=fake):
            assert volume_exists("docker") is False

    def test_remove_volume_failure(self):
        with patch(
            f"{_SVC_PREFIX}._run",
            side_effect=subprocess.CalledProcessError(1, "cmd", stderr="in use"),
        ):
            with pytest.raises(RuntimeError, match="Failed to remove volume"):
                remove_volume("docker")
