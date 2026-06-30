"""Interactive environment management commands for basecamp-workspace.

An environment maps a repo name to a setup command run when a new
implementation worktree is created.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import questionary

from basecamp_workspace import (
    EnvironmentConfig,
    get_environment,
    load_environments,
    remove_environment,
    set_environment,
)
from basecamp_workspace.ui import console, display_environments


def _current_repo_name() -> str | None:
    """Best-effort git repo basename for the current directory."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    top = result.stdout.strip()
    return Path(top).name if top else None


def _prompt_repo_name(default: str | None) -> str | None:
    """Prompt for a repo name, defaulting to the current repo when available."""
    name = questionary.text(
        "Repo name:",
        default=default or "",
        validate=lambda val: True if val.strip() else "Repo name is required",
    ).ask()
    return name.strip() if name else None


def _prompt_setup_command(default: str = "") -> str | None:
    """Prompt for a setup command. Returns None only when cancelled."""
    command = questionary.text("Setup command:", default=default).ask()
    return command if command is not None else None


def execute_environment_list() -> None:
    """List configured environments."""
    display_environments(load_environments())


def execute_environment_add() -> None:
    """Interactively add an environment."""
    console.print()
    console.print("[bold blue]Add an environment[/bold blue]")
    console.print()

    repo_name = _prompt_repo_name(_current_repo_name())
    if repo_name is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    command = _prompt_setup_command()
    if command is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return
    if not command.strip():
        console.print("\n[yellow]No command entered; nothing saved.[/yellow]")
        return

    set_environment(repo_name, EnvironmentConfig(setup=command))
    console.print(f"\n[green]✓[/green] Set environment for [bold]{repo_name}[/bold]")


def execute_environment_edit(repo_name: str) -> None:
    """Interactively edit an existing environment."""
    existing = get_environment(repo_name)
    if existing is None:
        console.print(f"[red]Error:[/red] Environment '{repo_name}' not found")
        raise SystemExit(1)

    console.print()
    console.print(f"[bold blue]Edit environment: {repo_name}[/bold blue]")
    console.print()

    command = _prompt_setup_command(default=existing.setup or "")
    if command is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    set_environment(repo_name, EnvironmentConfig(setup=command))
    if command.strip():
        console.print(f"\n[green]✓[/green] Updated environment for [bold]{repo_name}[/bold]")
    else:
        console.print(f"\n[green]✓[/green] Cleared environment for [bold]{repo_name}[/bold]")


def execute_environment_remove(repo_name: str) -> None:
    """Remove an environment after confirmation."""
    if get_environment(repo_name) is None:
        console.print(f"[red]Error:[/red] Environment '{repo_name}' not found")
        raise SystemExit(1)

    confirmed = questionary.confirm(f"Remove environment '{repo_name}'?", default=False).ask()
    if not confirmed:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    remove_environment(repo_name)
    console.print(f"[green]✓[/green] Removed environment [bold]{repo_name}[/bold]")


def run_environments_menu(exit_label: str = "Done") -> None:
    """Environment configuration menu."""
    while True:
        execute_environment_list()

        repo_names = list(load_environments().keys())

        action = questionary.select(
            "Environments:",
            choices=["Add", "Edit", "Remove", questionary.Separator(), exit_label],
        ).ask()

        if action is None or action == exit_label:
            return

        if action == "Add":
            execute_environment_add()
        elif action == "Edit":
            if not repo_names:
                console.print("[dim]No environments configured.[/dim]")
                continue
            name = questionary.select(
                "Edit which environment?",
                choices=[*repo_names, questionary.Separator(), "← Back"],
            ).ask()
            if name and name != "← Back":
                execute_environment_edit(name)
        elif action == "Remove":
            if not repo_names:
                console.print("[dim]No environments configured.[/dim]")
                continue
            name = questionary.select(
                "Remove which environment?",
                choices=[*repo_names, questionary.Separator(), "← Back"],
            ).ask()
            if name and name != "← Back":
                execute_environment_remove(name)
