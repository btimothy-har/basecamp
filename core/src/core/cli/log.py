"""Log command — quick capture to Logseq journal."""

from core.logseq import (
    append_block,
    ensure_journal_file,
    format_log_entry,
    resolve_graph_path,
    resolve_journal_path,
)
from core.ui import console


def execute_log(message: str, *, project: str | None = None) -> None:
    """Append a block to today's Logseq daily journal.

    Raises:
        LogseqNotConfiguredError: If logseq_graph is not set.
        LogseqGraphNotFoundError: If the graph directory doesn't exist.
    """
    graph_path = resolve_graph_path()
    journal_path = resolve_journal_path(graph_path)
    ensure_journal_file(journal_path)

    entry = format_log_entry(message, project=project)
    append_block(journal_path, entry)

    date_str = journal_path.stem.replace("_", "-")
    console.print(f"[green]✓[/green] Logged to {date_str} journal")
