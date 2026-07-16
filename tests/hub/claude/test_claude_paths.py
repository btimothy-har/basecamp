"""Tests for the Claude runtime path helpers (single promotable root)."""

from __future__ import annotations

from pathlib import Path

from basecamp.core.paths import swarm_runtime_dir
from basecamp.hub.claude.paths import (
    claude_pidfile_path,
    claude_runtime_dir,
    claude_sessions_db_path,
    claude_socket_path,
    claude_spawn_lock_path,
)


def test_all_paths_share_the_runtime_root(tmp_path: Path) -> None:
    root = claude_runtime_dir(home=tmp_path)

    assert root == tmp_path / ".pi" / "basecamp" / "claude"
    assert claude_socket_path(home=tmp_path) == root / "daemon.sock"
    assert claude_pidfile_path(home=tmp_path) == root / "daemon.pid"
    assert claude_spawn_lock_path(home=tmp_path) == root / "daemon.spawn.lock"
    assert claude_sessions_db_path(home=tmp_path) == root / "sessions.db"


def test_runtime_root_is_distinct_from_the_pi_swarm_root(tmp_path: Path) -> None:
    # The Claude daemon must never share a socket or database with the legacy Pi
    # swarm daemon (``~/.pi/basecamp/swarm``); it lives under a sibling ``claude`` dir.
    assert claude_runtime_dir(home=tmp_path) != swarm_runtime_dir(tmp_path)
    assert claude_sessions_db_path(home=tmp_path).name == "sessions.db"


def test_helpers_default_to_home_when_unparameterized() -> None:
    # Lazy resolution: no argument resolves under the real home at call time.
    assert claude_runtime_dir() == Path.home() / ".pi" / "basecamp" / "claude"
