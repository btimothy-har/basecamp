"""CLI command for session handoff."""

import sys

import rich_click as click

from core.exceptions import LauncherError
from core.handoff import execute_handoff
from core.ui import console, err_console


@click.command()
@click.option("--model", "-m", default="sonnet", help="Model for the new session (default: sonnet)")
def handoff(model: str) -> None:
    """Summarize the current session and spawn a new one.

    Forks the current conversation, generates a compact summary, and
    launches a new Claude session in a new terminal pane with that
    summary as context. The current session is not modified.

    \b
    Usage from within a Claude session:
        !handoff
        !handoff --model opus
    """
    try:
        name = execute_handoff(model=model)
        console.print(f"[bold green]Handoff complete[/bold green] → [cyan]{name}[/cyan]")
        console.print("[dim]New session spawned. You can /exit this one.[/dim]")
    except LauncherError as e:
        err_console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def main() -> None:
    """Standalone entry point for the handoff CLI."""
    handoff()
