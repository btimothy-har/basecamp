"""Interactive configuration menu for basecamp."""

from __future__ import annotations

import questionary

from basecamp.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from basecamp.config import load_projects
from basecamp.settings import settings
from basecamp.ui import console


def run_config_menu() -> None:
    """Top-level interactive config menu."""
    while True:
        console.print()
        section = questionary.select(
            "Configure:",
            choices=[
                "Projects",
                "Observer",
                questionary.Separator(),
                "Done",
            ],
        ).ask()

        if section is None or section == "Done":
            return

        if section == "Projects":
            _project_menu()
        elif section == "Observer":
            _observer_menu()


def _project_menu() -> None:
    """Project configuration sub-menu."""
    while True:
        execute_project_list()

        projects = load_projects()
        project_names = list(projects.keys())

        action = questionary.select(
            "Projects:",
            choices=[
                "Add",
                "Edit",
                "Remove",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Add":
            execute_project_add()
        elif action == "Edit":
            if not project_names:
                console.print("[dim]No projects configured.[/dim]")
                continue
            name = questionary.select(
                "Edit which project?",
                choices=[*project_names, questionary.Separator(), "← Back"],
            ).ask()
            if name and name != "← Back":
                execute_project_edit(name)
        elif action == "Remove":
            if not project_names:
                console.print("[dim]No projects configured.[/dim]")
                continue
            name = questionary.select(
                "Remove which project?",
                choices=[*project_names, questionary.Separator(), "← Back"],
            ).ask()
            if name and name != "← Back":
                execute_project_remove(name)


def _observer_menu() -> None:
    """Observer configuration sub-menu."""
    while True:
        obs = settings.observer

        console.print()
        console.print(f"  Extraction model: [bold]{obs.extraction_model}[/bold]")
        console.print(f"  Summary model:    [bold]{obs.summary_model}[/bold]")
        console.print(f"  Mode:             [bold]{obs.mode}[/bold]")

        action = questionary.select(
            "Observer:",
            choices=[
                "Set extraction model",
                "Set summary model",
                "Toggle mode",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set extraction model":
            model = questionary.text("Extraction model (provider:model):", default=obs.extraction_model).ask()
            if model:
                obs.extraction_model = model.strip()
                console.print(f"[green]✓[/green] Extraction model → [bold]{model.strip()}[/bold]")
        elif action == "Set summary model":
            model = questionary.text("Summary model (provider:model):", default=obs.summary_model).ask()
            if model:
                obs.summary_model = model.strip()
                console.print(f"[green]✓[/green] Summary model → [bold]{model.strip()}[/bold]")
        elif action == "Toggle mode":
            new_mode = "off" if obs.mode == "on" else "on"
            obs.mode = new_mode
            console.print(f"[green]✓[/green] Mode → [bold]{new_mode}[/bold]")
