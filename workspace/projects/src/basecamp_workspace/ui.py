"""UI display functions for basecamp-workspace."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table

from basecamp_workspace.environments import EnvironmentConfig
from basecamp_workspace.projects import ProjectConfig

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
        created = created.replace(tzinfo=UTC)
    days = (datetime.now(tz=UTC) - created).days
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
    table.add_column("Repo Root", style="blue")
    table.add_column("Additional Dirs", style="dim")
    table.add_column("Working Style", style="dim")

    for name, project in projects.items():
        additional_dirs = "\n".join(project.additional_dirs) if project.additional_dirs else "-"
        table.add_row(
            name,
            project.description or "-",
            project.repo_root,
            additional_dirs,
            project.working_style or "-",
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
