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


def worktrees_root(home: Path | None = None) -> Path:
    """Return the root under which workstream worktrees live (``~/.worktrees``).

    Single-sourced here (identical to the Pi ``constants.ts`` ``WORKTREES_ROOT``) so
    the ``~/.worktrees/<org>/<name>/<label>/`` layout has one Python source and
    cannot drift. ``home``-parameterized so tests can point ``$HOME`` at a temp dir.
    """
    return (home or Path.home()) / ".worktrees"


def shipped_prompts_dir() -> Path:
    """Directory holding the committed prompt files (``<repo>/claude/prompts``).

    Single source for the launcher (``system-prompt.md``) and the installer
    (``doctrine.md``). Prefers the installer-recorded root, falling back to this
    checkout when unset (editable/dev). Mirrors ``install._source_dir()``.
    """
    from basecamp.core.settings import settings  # noqa: PLC0415  # local: avoid import cycle

    install_dir = settings.install_dir
    base = Path(install_dir) if install_dir else Path(__file__).resolve().parents[3]
    return base / "claude" / "prompts"
