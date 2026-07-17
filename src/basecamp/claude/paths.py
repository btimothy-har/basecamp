"""Path helpers for the basecamp Claude foundation.

The Claude-side foundation is a full parallel to ``basecamp.core``: its state
lives under the user's Claude directory (``~/.claude``), not under ``~/.pi``.
This module owns the config-file location and any user-customization dirs the
Claude surface needs.

All helpers are ``home``-parameterized (not import-time constants) so tests can
point ``$HOME`` at a temp dir and the resolver picks it up at call time.
"""

from __future__ import annotations

from pathlib import Path

_CLAUDE_DIRNAME = ".claude"
_CONFIG_FILENAME = "basecamp.json"


def claude_dir(home: Path | None = None) -> Path:
    """Return the user's Claude directory (``~/.claude``)."""
    return (home or Path.home()) / _CLAUDE_DIRNAME


def config_path(home: Path | None = None) -> Path:
    """Return the basecamp Claude config file (``~/.claude/basecamp.json``)."""
    return claude_dir(home) / _CONFIG_FILENAME
