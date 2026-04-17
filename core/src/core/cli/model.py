"""Model alias management commands for basecamp."""

from __future__ import annotations

from rich.table import Table

from core.settings import settings
from core.ui import console


def execute_model_list() -> None:
    """List all configured model aliases."""
    models = settings.models
    if not models:
        console.print("\n[dim]No model aliases configured.[/dim]")
        console.print("[dim]Use [bold]basecamp model set <alias> <model-id>[/bold] to add one.[/dim]\n")
        return

    table = Table(title="Model Aliases", show_header=True, header_style="bold cyan")
    table.add_column("Alias", style="green")
    table.add_column("Model ID", style="blue")

    for alias, model_id in sorted(models.items()):
        table.add_row(alias, model_id)

    console.print()
    console.print(table)
    console.print()


def execute_model_set(alias: str, model_id: str) -> None:
    """Set a model alias."""
    models = settings.models
    is_update = alias in models
    models[alias] = model_id
    settings.models = models

    if is_update:
        console.print(f"[green]✓[/green] Updated [bold]{alias}[/bold] → {model_id}")
    else:
        console.print(f"[green]✓[/green] Set [bold]{alias}[/bold] → {model_id}")


def execute_model_remove(alias: str) -> None:
    """Remove a model alias."""
    models = settings.models
    if alias not in models:
        console.print(f"[red]Error:[/red] Alias '{alias}' not found")
        raise SystemExit(1)

    del models[alias]
    settings.models = models
    console.print(f"[green]✓[/green] Removed alias [bold]{alias}[/bold]")
