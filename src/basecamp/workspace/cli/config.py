"""Interactive project menu for basecamp-workspace."""

from __future__ import annotations

import questionary

from basecamp.workspace import load_projects
from basecamp.workspace.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
)
from basecamp.workspace.ui import console


def run_project_menu(exit_label: str = "Done") -> None:
    """Project configuration menu."""
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
                exit_label,
            ],
        ).ask()

        if action is None or action == exit_label:
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
