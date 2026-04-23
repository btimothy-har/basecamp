"""Interactive configuration menu for basecamp."""

from __future__ import annotations

import questionary

from basecamp.cli.language import (
    BUNDLED_LANGUAGES,
    execute_language_clear,
    execute_language_set,
    execute_language_show,
)
from basecamp.cli.model import execute_model_list, execute_model_remove, execute_model_set
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
                "Models",
                "Language",
                "Pi Command",
                "Worktree",
                "Observer",
                questionary.Separator(),
                "Done",
            ],
        ).ask()

        if section is None or section == "Done":
            return

        if section == "Projects":
            _project_menu()
        elif section == "Models":
            _model_menu()
        elif section == "Language":
            _language_menu()
        elif section == "Pi Command":
            _pi_command_menu()
        elif section == "Worktree":
            _worktree_menu()
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


def _model_menu() -> None:
    """Model alias configuration sub-menu."""
    while True:
        execute_model_list()

        action = questionary.select(
            "Models:",
            choices=[
                "Set",
                "Remove",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set":
            alias = questionary.text("Alias name (e.g. fast, balanced, complex):").ask()
            if not alias:
                continue
            model_id = questionary.text("Model ID (e.g. claude-haiku-4-5):").ask()
            if not model_id:
                continue
            execute_model_set(alias.strip(), model_id.strip())
        elif action == "Remove":
            models = settings.models
            if not models:
                console.print("[dim]No model aliases configured.[/dim]")
                continue
            alias = questionary.select(
                "Remove which alias?",
                choices=[*list(models.keys()), questionary.Separator(), "← Back"],
            ).ask()
            if alias and alias != "← Back":
                execute_model_remove(alias)


def _language_menu() -> None:
    """Language configuration sub-menu."""
    while True:
        execute_language_show()

        action = questionary.select(
            "Language:",
            choices=[
                "Set",
                "Clear",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set":
            choices = [*BUNDLED_LANGUAGES, "Other (custom)"]
            lang = questionary.select("Language:", choices=choices).ask()
            if lang is None:
                continue
            if lang == "Other (custom)":
                lang = questionary.text("Language name:").ask()
                if not lang:
                    continue
            execute_language_set(lang.strip())
        elif action == "Clear":
            execute_language_clear()


def _pi_command_menu() -> None:
    """Pi command configuration sub-menu."""
    while True:
        current = settings.pi_command
        if current:
            console.print(f"\nPi command: [bold green]{current}[/bold green]")
        else:
            console.print("\n[dim]No custom pi command (using default 'pi').[/dim]")

        action = questionary.select(
            "Pi Command:",
            choices=[
                "Set",
                "Clear",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set":
            value = questionary.text(
                "Pi command (path or name):",
                default=current or "pi",
            ).ask()
            if value and value.strip():
                settings.pi_command = value.strip()
                console.print(f"[green]✓[/green] Pi command → [bold]{value.strip()}[/bold]")
        elif action == "Clear":
            settings.pi_command = None
            console.print("[green]✓[/green] Pi command cleared (using default 'pi')")


def _worktree_menu() -> None:
    """Worktree configuration sub-menu."""
    while True:
        current = settings.worktree_branch_prefix
        if current:
            console.print(f"\nBranch prefix: [bold green]{current}[/bold green]")
        else:
            console.print("\n[dim]No custom prefix (using default 'wt/').[/dim]")

        action = questionary.select(
            "Worktree:",
            choices=[
                "Set prefix",
                "Clear",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set prefix":
            value = questionary.text(
                "Branch prefix (e.g. 'feature/', 'wt/'):",
                default=current or "wt/",
            ).ask()
            if value is not None and value.strip():
                settings.worktree_branch_prefix = value.strip()
                console.print(f"[green]✓[/green] Branch prefix → [bold]{value.strip()}[/bold]")
        elif action == "Clear":
            settings.worktree_branch_prefix = None
            console.print("[green]✓[/green] Branch prefix cleared (using default 'wt/')")


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
