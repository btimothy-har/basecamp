"""UI display functions for basecamp."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from core.config import Config
from core.git import WorktreeInfo

# Console instances for output
console = Console()
err_console = Console(stderr=True)


def display_projects(config: Config) -> None:
    """Display available projects in a rich table."""
    table = Table(title="Available Projects", show_header=True, header_style="bold cyan")
    table.add_column("Project", style="green")
    table.add_column("Description")
    table.add_column("Primary Directory", style="blue")
    table.add_column("Working Style", style="dim")

    for name, project in config.projects.items():
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


def display_worktrees(project: str, worktrees: list[WorktreeInfo]) -> None:
    """Display worktrees for a project in a rich table.

    Args:
        project: The project name.
        worktrees: List of worktrees to display.
    """
    if not worktrees:
        console.print(f"\n[yellow]No worktrees found for project '{project}'[/yellow]\n")
        return

    table = Table(
        title=f"Worktrees for '{project}'",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Label", style="green")
    table.add_column("Created", style="dim")
    table.add_column("Path", style="dim")

    for wt in worktrees:
        table.add_row(
            wt.name,
            wt.created_at.strftime("%Y-%m-%d %H:%M"),
            str(wt.path),
        )

    console.print()
    console.print(table)
    console.print()


def display_all_worktrees(all_worktrees: dict[str, list[WorktreeInfo]]) -> None:
    """Display all worktrees across all repositories.

    Args:
        all_worktrees: Dictionary mapping repo names to lists of WorktreeInfo.
    """
    if not all_worktrees:
        console.print("\n[yellow]No worktrees found[/yellow]\n")
        return

    table = Table(
        title="All Worktrees",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Repository", style="magenta")
    table.add_column("Label", style="green")
    table.add_column("Created", style="dim")

    for repo_name in sorted(all_worktrees.keys()):
        worktrees = all_worktrees[repo_name]
        for i, wt in enumerate(worktrees):
            # Only show repo name on first row of each group
            repo_display = repo_name if i == 0 else ""
            table.add_row(
                repo_display,
                wt.name,
                wt.created_at.strftime("%Y-%m-%d %H:%M"),
            )

    console.print()
    console.print(table)
    console.print()
