"""Daemon liveness and spawn-lock safety for doctor repairs."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import basecamp.doctor.process as process
from basecamp.doctor.process import DaemonSpawnLock, DaemonState, inspect_daemon


def test_healthy_daemon_is_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process, "_health", lambda _path, **_kwargs: 23)

    status = inspect_daemon(tmp_path / "sock", tmp_path / "pid", tmp_path / "lock")

    assert status.state is DaemonState.LIVE
    assert status.protocol == 23


def test_live_validated_pid_without_health_is_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pid_path = tmp_path / "daemon.pid"
    pid_path.write_text("123\n", encoding="utf-8")
    monkeypatch.setattr(process, "_health", lambda _path, **_kwargs: None)
    monkeypatch.setattr(process, "_pid_alive", lambda pid: pid == 123)
    monkeypatch.setattr(process, "_pid_matches_socket", lambda pid, _path: pid == 123)

    status = inspect_daemon(tmp_path / "sock", pid_path, tmp_path / "lock")

    assert status.state is DaemonState.AMBIGUOUS
    assert "health check failed" in (status.detail or "")


def test_absent_daemon_is_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process, "_health", lambda _path, **_kwargs: None)
    monkeypatch.setattr(process, "_find_daemon_pid", lambda _path: (None, False))

    status = inspect_daemon(tmp_path / "sock", tmp_path / "pid", tmp_path / "lock")

    assert status.state is DaemonState.DOWN


def test_spawn_lock_or_failed_process_scan_is_ambiguous(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process, "_health", lambda _path, **_kwargs: None)
    monkeypatch.setattr(process, "_find_daemon_pid", lambda _path: (None, False))
    lock_path = tmp_path / "lock"
    lock_path.write_text("{}", encoding="utf-8")

    assert inspect_daemon(tmp_path / "sock", tmp_path / "pid", lock_path).state is DaemonState.AMBIGUOUS

    lock_path.unlink()
    monkeypatch.setattr(process, "_find_daemon_pid", lambda _path: (None, True))
    assert inspect_daemon(tmp_path / "sock", tmp_path / "pid", lock_path).state is DaemonState.AMBIGUOUS


def test_spawn_lock_refreshes_and_releases_only_its_own_file(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.spawn.lock"

    with DaemonSpawnLock(lock_path) as lock:
        first = json.loads(lock_path.read_text(encoding="utf-8"))
        lock.refresh(force=True)
        second = json.loads(lock_path.read_text(encoding="utf-8"))
        assert first["pid"] == second["pid"]
        assert second["ts"] >= first["ts"]
    assert not lock_path.exists()

    with DaemonSpawnLock(lock_path):
        lock_path.write_text('{"pid": 999, "ts": 1}', encoding="utf-8")
    assert lock_path.exists()


@pytest.mark.parametrize(
    "command",
    [
        "basecamp hub --uds /tmp/basecamp.sock --db /tmp/db",
        "/usr/local/bin/basecamp hub --uds=/tmp/basecamp.sock",
        "basecamp swarm daemon --uds /tmp/basecamp.sock",
    ],
)
def test_daemon_command_matches_supported_forms(command: str) -> None:
    assert process._is_daemon_command(command, Path("/tmp/basecamp.sock")) is True


@pytest.mark.parametrize(
    "command",
    [
        "basecamp hub --uds /tmp/other.sock",
        "basecamp companion --snapshot /tmp/basecamp.sock",
        "cat /tmp/basecamp.sock",
    ],
)
def test_daemon_command_rejects_unrelated_processes(command: str) -> None:
    assert process._is_daemon_command(command, Path("/tmp/basecamp.sock")) is False


def test_spawn_lock_heartbeat_covers_blocking_operation(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.spawn.lock"

    with DaemonSpawnLock(lock_path) as lock:
        first = json.loads(lock_path.read_text(encoding="utf-8"))
        lock.run_while_refreshing(lambda: time.sleep(0.03), interval=0.005)
        refreshed = json.loads(lock_path.read_text(encoding="utf-8"))
        assert refreshed["ts"] > first["ts"]

    assert not lock_path.exists()


def test_spawn_lock_refuses_existing_owner(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.spawn.lock"
    lock_path.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        with DaemonSpawnLock(lock_path):
            pass
    assert lock_path.read_text(encoding="utf-8") == "existing"
