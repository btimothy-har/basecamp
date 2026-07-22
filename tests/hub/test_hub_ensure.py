"""Python hub ensure contract shared with the TypeScript client."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pytest import MonkeyPatch

from basecamp.hub.ensure import (
    EnsureHubDeps,
    HubEnsureError,
    HubHealth,
    HubPaths,
    _acquire_spawn_lock,
    _is_daemon_command,
    _release_spawn_lock,
    default_ensure_deps,
    ensure_hub,
)
from basecamp.hub.frames import PROTOCOL_VERSION


class _Clock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    def wall_ms(self) -> int:
        return 1_700_000_000_000 + int(self.elapsed * 1000)

    def sleep(self, seconds: float) -> None:
        self.elapsed += seconds


def _paths(tmp_path: Path) -> HubPaths:
    return HubPaths(
        runtime_dir=tmp_path / "swarm",
        socket_path=tmp_path / "swarm" / "daemon.sock",
        spawn_lock_path=tmp_path / "swarm" / "daemon.spawn.lock",
        pid_path=tmp_path / "swarm" / "daemon.pid",
        db_path=tmp_path / "swarm" / "daemon.db",
    )


def _deps(
    clock: _Clock,
    *,
    health_ping,
    spawn_hub=lambda _paths: None,
    terminate_hub=lambda _paths: None,
    pid_exists=lambda _pid: False,
) -> EnsureHubDeps:
    return EnsureHubDeps(
        health_ping=health_ping,
        spawn_hub=spawn_hub,
        terminate_hub=terminate_hub,
        pid_exists=pid_exists,
        wall_clock_ms=clock.wall_ms,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )


def test_spawn_lock_path_matches_typescript_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "pi/core/hub/paths.ts").read_text(encoding="utf-8")
    assert 'spawnLockPath: path.join(runtimeDir, "daemon.spawn.lock")' in source


def test_ensure_hub_reuses_matching_daemon_without_lock_or_spawn(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    clock = _Clock()
    spawns: list[HubPaths] = []

    result = ensure_hub(
        paths=paths,
        deps=_deps(
            clock,
            health_ping=lambda _path, _timeout: HubHealth(ok=True, protocol=PROTOCOL_VERSION),
            spawn_hub=spawns.append,
        ),
    )

    assert result == paths.socket_path
    assert spawns == []
    assert not paths.spawn_lock_path.exists()


def test_default_spawn_command_is_detached_and_silent(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def popen(command: list[str], **kwargs: object) -> object:
        calls.append((command, kwargs))
        return object()

    monkeypatch.setattr("basecamp.hub.ensure.subprocess.Popen", popen)
    paths = _paths(tmp_path)
    default_ensure_deps().spawn_hub(paths)

    assert calls == [
        (
            [
                "basecamp",
                "hub",
                "--uds",
                str(paths.socket_path),
                "--pidfile",
                str(paths.pid_path),
                "--db",
                str(paths.db_path),
            ],
            {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "start_new_session": True,
                "close_fds": True,
            },
        )
    ]


def test_concurrent_ensures_spawn_exactly_one_daemon(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    healthy = threading.Event()
    spawn_count = 0
    count_lock = threading.Lock()

    def health_ping(_path: Path, _timeout: float) -> HubHealth:
        return HubHealth(ok=healthy.is_set(), protocol=PROTOCOL_VERSION if healthy.is_set() else None)

    def spawn_hub(_paths: HubPaths) -> None:
        nonlocal spawn_count
        with count_lock:
            spawn_count += 1
        time.sleep(0.02)
        healthy.set()

    deps = EnsureHubDeps(
        health_ping=health_ping,
        spawn_hub=spawn_hub,
        terminate_hub=lambda _paths: None,
        pid_exists=lambda pid: pid == os.getpid(),
        wall_clock_ms=lambda: time.time_ns() // 1_000_000,
        monotonic=time.monotonic,
        sleep=time.sleep,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: ensure_hub(paths=paths, deps=deps), range(2)))

    assert results == [paths.socket_path, paths.socket_path]
    assert spawn_count == 1
    assert not paths.spawn_lock_path.exists()


def test_ensure_hub_reclaims_stale_lock_and_uses_contract_modes(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.runtime_dir.mkdir(parents=True)
    clock = _Clock()
    paths.spawn_lock_path.write_text(
        json.dumps({"pid": 999999, "ts": clock.wall_ms() - 120_000}),
        encoding="utf-8",
    )
    healthy = False

    def spawn_hub(locked_paths: HubPaths) -> None:
        nonlocal healthy
        lock = json.loads(locked_paths.spawn_lock_path.read_text(encoding="utf-8"))
        assert set(lock) == {"pid", "ts"}
        assert lock["pid"] == os.getpid()
        assert stat.S_IMODE(locked_paths.spawn_lock_path.stat().st_mode) == 0o600
        healthy = True

    result = ensure_hub(
        paths=paths,
        deps=_deps(
            clock,
            health_ping=lambda _path, _timeout: HubHealth(ok=healthy, protocol=PROTOCOL_VERSION if healthy else None),
            spawn_hub=spawn_hub,
        ),
    )

    assert result == paths.socket_path
    assert stat.S_IMODE(paths.runtime_dir.stat().st_mode) == 0o700
    assert not paths.spawn_lock_path.exists()


def test_ensure_hub_restarts_protocol_mismatch(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    clock = _Clock()
    protocol = 999
    events: list[str] = []

    def terminate(_paths: HubPaths) -> None:
        events.append("terminate")

    def spawn(_paths: HubPaths) -> None:
        nonlocal protocol
        events.append("spawn")
        protocol = PROTOCOL_VERSION

    result = ensure_hub(
        paths=paths,
        deps=_deps(
            clock,
            health_ping=lambda _path, _timeout: HubHealth(ok=True, protocol=protocol),
            spawn_hub=spawn,
            terminate_hub=terminate,
        ),
    )

    assert result == paths.socket_path
    assert events == ["terminate", "spawn"]


def test_protocol_restart_gets_fresh_post_spawn_readiness_budget(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    clock = _Clock()
    ready_at: float | None = None
    events: list[str] = []

    def health_ping(_path: Path, _timeout: float) -> HubHealth:
        if ready_at is None:
            return HubHealth(ok=True, protocol=999)
        is_ready = clock.elapsed >= ready_at
        return HubHealth(ok=is_ready, protocol=PROTOCOL_VERSION if is_ready else None)

    def terminate(_paths: HubPaths) -> None:
        events.append("terminate")
        clock.sleep(0.9)

    def spawn(_paths: HubPaths) -> None:
        nonlocal ready_at
        events.append("spawn")
        ready_at = clock.elapsed + 0.35

    result = ensure_hub(
        paths=paths,
        deps=_deps(
            clock,
            health_ping=health_ping,
            spawn_hub=spawn,
            terminate_hub=terminate,
        ),
        startup_timeout=1.0,
        lock_retry=0.1,
    )

    assert result == paths.socket_path
    assert events == ["terminate", "spawn"]
    assert clock.elapsed >= 1.25


def test_ensure_hub_reports_persistent_mismatch_and_timeout(tmp_path: Path) -> None:
    mismatch_paths = _paths(tmp_path / "mismatch")
    mismatch_clock = _Clock()
    with pytest.raises(HubEnsureError, match="protocol mismatch"):
        ensure_hub(
            paths=mismatch_paths,
            deps=_deps(
                mismatch_clock,
                health_ping=lambda _path, _timeout: HubHealth(ok=True, protocol=999),
            ),
        )

    timeout_paths = _paths(tmp_path / "timeout")
    timeout_clock = _Clock()
    with pytest.raises(HubEnsureError, match="Timed out"):
        ensure_hub(
            paths=timeout_paths,
            deps=_deps(
                timeout_clock,
                health_ping=lambda _path, _timeout: HubHealth(ok=False),
            ),
            startup_timeout=0.2,
        )


def test_runtime_setup_error_uses_hub_ensure_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    clock = _Clock()
    health_calls: list[Path] = []
    spawns: list[HubPaths] = []

    def fail_chmod(_path: Path, _mode: int) -> None:
        raise PermissionError("denied")

    def health_ping(path: Path, _timeout: float) -> HubHealth:
        health_calls.append(path)
        return HubHealth(ok=False)

    monkeypatch.setattr("basecamp.hub.ensure.os.chmod", fail_chmod)

    with pytest.raises(HubEnsureError, match="runtime directory") as error:
        ensure_hub(
            paths=paths,
            deps=_deps(clock, health_ping=health_ping, spawn_hub=spawns.append),
        )

    assert isinstance(error.value.__cause__, PermissionError)
    assert health_calls == []
    assert spawns == []


def test_spawn_lock_error_uses_hub_ensure_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    clock = _Clock()
    health_calls: list[Path] = []
    spawns: list[HubPaths] = []

    def health_ping(path: Path, _timeout: float) -> HubHealth:
        health_calls.append(path)
        return HubHealth(ok=False)

    def fail_lock(_path: Path, _now_ms: int) -> tuple[int, tuple[int, int]]:
        raise PermissionError("denied")

    monkeypatch.setattr("basecamp.hub.ensure._acquire_spawn_lock", fail_lock)

    with pytest.raises(HubEnsureError, match="spawn lock") as error:
        ensure_hub(
            paths=paths,
            deps=_deps(clock, health_ping=health_ping, spawn_hub=spawns.append),
        )

    assert isinstance(error.value.__cause__, PermissionError)
    assert health_calls == [paths.socket_path]
    assert spawns == []


def test_stale_spawn_lock_cleanup_error_uses_hub_ensure_error(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    paths = _paths(tmp_path)
    paths.runtime_dir.mkdir(parents=True)
    paths.spawn_lock_path.write_text('{"pid":999999,"ts":0}', encoding="utf-8")
    clock = _Clock()
    spawns: list[HubPaths] = []

    def fail_unlink(_path: Path) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr("basecamp.hub.ensure._unlink", fail_unlink)

    with pytest.raises(HubEnsureError, match="spawn lock") as error:
        ensure_hub(
            paths=paths,
            deps=_deps(
                clock,
                health_ping=lambda _path, _timeout: HubHealth(ok=False),
                spawn_hub=spawns.append,
            ),
        )

    assert isinstance(error.value.__cause__, PermissionError)
    assert spawns == []


def test_spawn_lock_release_does_not_unlink_replacement(tmp_path: Path) -> None:
    lock_path = tmp_path / "daemon.spawn.lock"
    fd, identity = _acquire_spawn_lock(lock_path, 100)
    lock_path.unlink()
    lock_path.write_text('{"pid":2,"ts":200}', encoding="utf-8")

    _release_spawn_lock(fd, lock_path, identity)

    assert lock_path.read_text(encoding="utf-8") == '{"pid":2,"ts":200}'


def test_daemon_command_matching_requires_command_and_socket() -> None:
    socket_path = Path("/tmp/basecamp/daemon.sock")
    assert _is_daemon_command(f"/bin/basecamp hub --uds {socket_path}", socket_path)
    assert _is_daemon_command(f"basecamp swarm daemon --uds={socket_path}", socket_path)
    assert not _is_daemon_command("basecamp agents", socket_path)
    assert not _is_daemon_command("basecamp hub --uds /tmp/other.sock", socket_path)
