"""Ensure-daemon algorithm tests (hermetic, injected clock/ping/spawn/terminate)."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from basecamp.hub.claude.client.errors import DaemonProtocolMismatchError, DaemonUnavailableError
from basecamp.hub.claude.client.paths import DaemonPaths, daemon_paths
from basecamp.hub.claude.client.spawn import ensure_daemon
from basecamp.hub.claude.client.transport import HealthResult

PROTOCOL = 23


def _paths(tmp_path: Path) -> DaemonPaths:
    return daemon_paths(home=tmp_path)


class _Ping:
    """A ping callable that yields queued results, repeating the last."""

    def __init__(self, results: list[HealthResult]) -> None:
        self._results = results
        self.calls = 0

    def __call__(self, _socket: str, _timeout: float) -> HealthResult:
        self.calls += 1
        index = min(self.calls - 1, len(self._results) - 1)
        return self._results[index]


class _Recorder:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_args: object) -> None:
        self.calls += 1


def _tick(step: float = 0.0) -> Callable[[], float]:
    counter = {"t": 0.0}

    def clock() -> float:
        value = counter["t"]
        counter["t"] += step
        return value

    return clock


def test_returns_immediately_when_daemon_already_healthy(tmp_path: Path) -> None:
    ping = _Ping([HealthResult(ok=True, protocol=PROTOCOL)])
    spawn = _Recorder()

    socket = ensure_daemon(_paths(tmp_path), protocol_version=PROTOCOL, ping=ping, spawn=spawn)

    assert socket == str(_paths(tmp_path).socket)
    assert spawn.calls == 0
    assert ping.calls == 1


def test_spawns_when_absent_then_becomes_healthy(tmp_path: Path) -> None:
    ping = _Ping(
        [
            HealthResult(ok=False),  # initial probe
            HealthResult(ok=False),  # under the lock
            HealthResult(ok=True, protocol=PROTOCOL),  # after spawn
        ]
    )
    spawn = _Recorder()
    terminate = _Recorder()

    socket = ensure_daemon(
        _paths(tmp_path),
        protocol_version=PROTOCOL,
        ping=ping,
        spawn=spawn,
        terminate=terminate,
        sleep=lambda _s: None,
    )

    assert socket == str(_paths(tmp_path).socket)
    assert spawn.calls == 1
    assert terminate.calls == 0


def test_terminates_incompatible_daemon_then_respawns(tmp_path: Path) -> None:
    ping = _Ping(
        [
            HealthResult(ok=True, protocol=1),  # initial: live but wrong protocol
            HealthResult(ok=True, protocol=1),  # under the lock: still wrong
            HealthResult(ok=True, protocol=PROTOCOL),  # after terminate + spawn
        ]
    )
    spawn = _Recorder()
    terminate = _Recorder()

    socket = ensure_daemon(
        _paths(tmp_path),
        protocol_version=PROTOCOL,
        ping=ping,
        spawn=spawn,
        terminate=terminate,
        sleep=lambda _s: None,
    )

    assert socket == str(_paths(tmp_path).socket)
    assert terminate.calls == 1
    assert spawn.calls == 1


def test_protocol_mismatch_after_spawn_raises(tmp_path: Path) -> None:
    ping = _Ping(
        [
            HealthResult(ok=False),
            HealthResult(ok=False),
            HealthResult(ok=True, protocol=99),  # comes up, but wrong protocol
        ]
    )

    with pytest.raises(DaemonProtocolMismatchError):
        ensure_daemon(
            _paths(tmp_path),
            protocol_version=PROTOCOL,
            ping=ping,
            spawn=_Recorder(),
            sleep=lambda _s: None,
        )


def test_times_out_when_never_healthy(tmp_path: Path) -> None:
    ping = _Ping([HealthResult(ok=False)])

    with pytest.raises(DaemonUnavailableError):
        ensure_daemon(
            _paths(tmp_path),
            protocol_version=PROTOCOL,
            ping=ping,
            spawn=_Recorder(),
            sleep=lambda _s: None,
            monotonic=_tick(step=2.0),  # crosses the 5 s deadline in a few ticks
        )


def test_adopts_daemon_brought_up_by_lock_holder(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    # A live contender holds the lock (our own pid, fresh timestamp) and its
    # daemon is already healthy: we adopt it rather than double-spawning.
    paths.spawn_lock.write_text(
        json.dumps({"pid": os.getpid(), "ts": 0}),
        encoding="utf-8",
    )
    ping = _Ping(
        [
            HealthResult(ok=False),  # initial probe fails → enter loop
            HealthResult(ok=True, protocol=PROTOCOL),  # contender's daemon is up
        ]
    )
    spawn = _Recorder()

    socket = ensure_daemon(
        paths,
        protocol_version=PROTOCOL,
        ping=ping,
        spawn=spawn,
        sleep=lambda _s: None,
        wall_clock=lambda: 0.0,
    )

    assert socket == str(paths.socket)
    assert spawn.calls == 0
    # We must not remove a live contender's lock.
    assert paths.spawn_lock.exists()


def test_reclaims_stale_lock_then_spawns(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    paths.runtime_dir.mkdir(parents=True, exist_ok=True)
    # Stale lock: a dead pid → we reclaim it and spawn ourselves.
    paths.spawn_lock.write_text(
        json.dumps({"pid": 999999, "ts": 0}),
        encoding="utf-8",
    )
    ping = _Ping(
        [
            HealthResult(ok=False),  # initial probe
            HealthResult(ok=False),  # under the reclaimed lock
            HealthResult(ok=True, protocol=PROTOCOL),  # after spawn
        ]
    )
    spawn = _Recorder()

    socket = ensure_daemon(
        paths,
        protocol_version=PROTOCOL,
        ping=ping,
        spawn=spawn,
        sleep=lambda _s: None,
        wall_clock=lambda: 0.0,
    )

    assert socket == str(paths.socket)
    assert spawn.calls == 1
    # The lock we acquired is released in the finally block.
    assert not paths.spawn_lock.exists()
