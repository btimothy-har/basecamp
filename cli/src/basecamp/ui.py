"""UI display functions for basecamp."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from basecamp.config.project import ProjectConfig

# Console instances for output
console = Console()
err_console = Console(stderr=True)


def format_age(created_at: str) -> str:
    """Human-readable age from an ISO timestamp: 'today', 'yesterday', 'Nd ago'."""
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days = (datetime.now(tz=timezone.utc) - created).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days}d ago"


def display_projects(projects: dict[str, ProjectConfig]) -> None:
    """Display available projects in a rich table."""
    table = Table(title="Available Projects", show_header=True, header_style="bold cyan")
    table.add_column("Project", style="green")
    table.add_column("Description")
    table.add_column("Primary Directory", style="blue")
    table.add_column("Working Style", style="dim")

    for name, project in projects.items():
        primary_dir = project.dirs[0] if project.dirs else "-"
        table.add_row(
            name,
            project.description or "-",
            primary_dir,
            project.working_style or "-",
        )

    console.print()
    console.print(table)
    console.print()
