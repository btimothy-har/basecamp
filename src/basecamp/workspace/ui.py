"""UI display functions for basecamp-workspace."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from basecamp.core.projects import ProjectConfig
from basecamp.workspace.environments import EnvironmentConfig

# Console instances for output
console = Console()
err_console = Console(stderr=True)


def display_projects(projects: dict[str, ProjectConfig]) -> None:
    """Display available projects in a rich table."""
    table = Table(title="Available Projects", show_header=True, header_style="bold cyan")
    table.add_column("Project", style="green")
    table.add_column("Description")
    table.add_column("Repo Root", style="blue")
    table.add_column("Additional Dirs", style="dim")

    for name, project in projects.items():
        additional_dirs = "\n".join(project.additional_dirs) if project.additional_dirs else "-"
        table.add_row(
            name,
            project.description or "-",
            project.repo_root,
            additional_dirs,
        )

    console.print()
    console.print(table)
    console.print()


def display_environments(environments: dict[str, EnvironmentConfig]) -> None:
    """Display configured environments in a rich table."""
    table = Table(title="Configured Environments", show_header=True, header_style="bold cyan")
    table.add_column("Repo", style="green")
    table.add_column("Setup Command")

    for name, env in environments.items():
        table.add_row(name, env.setup or "-")

    console.print()
    console.print(table)
    console.print()
