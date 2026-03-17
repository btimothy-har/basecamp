"""Logseq graph operations — journal file resolution and block writing."""

from __future__ import annotations

import datetime
from pathlib import Path

from core.exceptions import LogseqGraphNotFoundError, LogseqNotConfiguredError
from core.settings import settings


def resolve_graph_path() -> Path:
    """Read the logseq_graph setting and resolve to an absolute path.

    Raises:
        LogseqNotConfiguredError: If the setting is not set.
        LogseqGraphNotFoundError: If the directory does not exist.
    """
    relative = settings.logseq_graph
    if not relative:
        raise LogseqNotConfiguredError

    graph_path = Path.home() / relative
    if not graph_path.is_dir():
        raise LogseqGraphNotFoundError(graph_path)

    return graph_path


def resolve_journal_path(graph_path: Path, date: datetime.date | None = None) -> Path:
    """Return the journal file path for the given date (defaults to today)."""
    target = date or datetime.datetime.now(tz=datetime.UTC).date()
    filename = target.strftime("%Y_%m_%d") + ".md"
    return graph_path / "journals" / filename


def ensure_journal_file(journal_path: Path) -> None:
    """Create the journal file and parent directories if they don't exist."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    if not journal_path.exists():
        journal_path.touch()


def append_block(journal_path: Path, text: str) -> None:
    """Append a Logseq block to the journal file."""
    block = f"- {text}\n"

    existing = journal_path.read_text()
    if existing and not existing.endswith("\n"):
        block = "\n" + block

    with journal_path.open("a") as f:
        f.write(block)


def format_log_entry(message: str, *, project: str | None = None) -> str:
    """Format a log entry with optional project page reference."""
    if project:
        return f"[[{project}]] {message}"
    return message
