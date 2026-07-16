"""Claude runtime path helpers, rooted at a single promotable constant.

Everything the Claude Code session lifecycle writes — the daemon socket, its
pidfile, the spawn lock, the daemon database, and the hook failure log — lives
under ONE root. Transitionally that root sits beside the legacy Pi runtime under
``~/.pi/basecamp/claude`` so the two daemons never share a socket or database;
promotion later is a single edit of ``_CLAUDE_RUNTIME_SEGMENTS`` (drop ``.pi``),
after which the Pi side can be removed outright.

Helpers are lazy and ``home``-parameterized (not import-time constants) so tests
that monkeypatch ``$HOME`` — and the ensure-daemon client — resolve paths at call
time rather than at import.
"""

from __future__ import annotations

from pathlib import Path

#: The single promotable root, relative to ``home``. Flip these segments (drop
#: ``.pi``) at promotion; every helper below is derived from this one place.
_CLAUDE_RUNTIME_SEGMENTS: tuple[str, ...] = (".pi", "basecamp", "claude")


def claude_runtime_dir(home: Path | None = None) -> Path:
    """Return the Claude hub daemon's runtime directory."""
    return (home or Path.home()).joinpath(*_CLAUDE_RUNTIME_SEGMENTS)


def claude_socket_path(home: Path | None = None) -> Path:
    """Return the Claude daemon's Unix domain socket path."""
    return claude_runtime_dir(home) / "daemon.sock"


def claude_pidfile_path(home: Path | None = None) -> Path:
    """Return the Claude daemon's PID file path."""
    return claude_runtime_dir(home) / "daemon.pid"


def claude_spawn_lock_path(home: Path | None = None) -> Path:
    """Return the exclusive-create spawn-lock path serializing daemon starts."""
    return claude_runtime_dir(home) / "daemon.spawn.lock"


def claude_daemon_db_path(home: Path | None = None) -> Path:
    """Return the Claude daemon's SQLite database path (sessions + episodes)."""
    return claude_runtime_dir(home) / "daemon.db"
