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
from basecamp.ui import console


def run_config_menu() -> None:
    """Top-level interactive config menu."""
    while True:
        console.print()
        section = questionary.select(
            "Configure:",
            choices=[
                "Projects",
                questionary.Separator(),
                "Done",
            ],
        ).ask()

        if section is None or section == "Done":
            return

        if section == "Projects":
            _project_menu()


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
