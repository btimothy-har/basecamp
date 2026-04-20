"""Language configuration commands for basecamp."""

from __future__ import annotations

from basecamp.settings import settings
from basecamp.ui import console

# Languages with bundled prompt files in the extension.
BUNDLED_LANGUAGES = ["singlish"]


def execute_language_show() -> None:
    """Show the currently configured language."""
    lang = settings.language
    if lang:
        console.print(f"\nLanguage: [bold green]{lang}[/bold green]\n")
    else:
        console.print("\n[dim]No language configured (using standard English).[/dim]")
        console.print("[dim]Use [bold]basecamp language set <name>[/bold] to configure one.[/dim]\n")


def execute_language_set(name: str) -> None:
    """Set the conversation language."""
    if name not in BUNDLED_LANGUAGES:
        console.print(f"[yellow]Warning:[/yellow] '{name}' is not a bundled language ({', '.join(BUNDLED_LANGUAGES)}).")
        console.print("[dim]It will work if you provide a matching prompt file in ~/.pi/languages/[/dim]")

    settings.language = name
    console.print(f"[green]✓[/green] Language set to [bold]{name}[/bold]")


def execute_language_clear() -> None:
    """Clear the language setting (revert to standard English)."""
    settings.language = None
    console.print("[green]✓[/green] Language cleared (standard English)")
