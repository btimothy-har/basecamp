"""UI display functions for basecamp."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from basecamp.config.project import ProjectConfig

# Console instances for output
console = Console()
err_console = Console(stderr=True)


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
