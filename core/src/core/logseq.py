"""Logseq graph operations — journal file resolution and block writing."""

from __future__ import annotations

import datetime
import zoneinfo
from pathlib import Path

from core.config.directories import resolve_dir
from core.exceptions import (
    LauncherError,
    LogseqGraphNotFoundError,
    LogseqNotConfiguredError,
)
from core.settings import settings


def resolve_graph_path() -> Path:
    """Resolve the logseq_graph setting to an absolute path.

    The setting is expected to be a home-relative path (as stored by
    ``basecamp setup``). It is resolved via ``resolve_dir`` which
    validates containment within ``$HOME``.

    Raises:
        LogseqNotConfiguredError: If the setting is not set.
        LogseqGraphNotFoundError: If the directory does not exist or
            the path escapes ``$HOME``.
    """
    graph_setting = settings.logseq_graph
    if not graph_setting:
        raise LogseqNotConfiguredError

    try:
        graph_path = resolve_dir(graph_setting)
    except LauncherError:
        raise LogseqGraphNotFoundError(Path(graph_setting)) from None

    if not graph_path.is_dir():
        raise LogseqGraphNotFoundError(graph_path)

    return graph_path


def today() -> datetime.date:
    """Return today's date in the user's configured timezone.

    Falls back to the system's local timezone if no timezone is configured
    or the configured value is invalid.
    """
    tz_name = settings.timezone
    if tz_name:
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            return datetime.datetime.now(tz=tz).date()
        except (KeyError, zoneinfo.ZoneInfoNotFoundError):
            pass
    return datetime.datetime.now().astimezone().date()


def resolve_journal_path(graph_path: Path, date: datetime.date | None = None) -> Path:
    """Return the journal file path for the given date (defaults to today)."""
    target = date or today()
    filename = target.strftime("%Y_%m_%d") + ".md"
    return graph_path / "journals" / filename


def ensure_journal_file(journal_path: Path) -> None:
    """Create the journal file and parent directories if they don't exist."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if not journal_path.exists():
        journal_path.touch()


def append_block(journal_path: Path, text: str) -> None:
    """Append a Logseq block to the journal file.

    Uses ``a+`` so the call succeeds even if the file doesn't exist yet
    (though callers normally ensure it via ``ensure_journal_file``).
    Reads and writes in a single open to avoid a race between checking
    the trailing newline and appending the block.
    """
    block = f"- {text}\n"
    with journal_path.open("a+") as f:
        f.seek(0)
        existing = f.read()
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(block)


def format_log_entry(message: str, *, project: str | None = None) -> str:
    """Format a log entry with optional project page reference."""
    if project:
        return f"[[{project}]] {message}"
    return message
