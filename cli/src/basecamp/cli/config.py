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
from basecamp.settings import ProviderConfig, settings
from basecamp.ui import console

_PROVIDER_LABELS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "openrouter": "OpenRouter",
}


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
        providers = obs.provider_configs
        openai_cfg = providers["openai"]
        anthropic_cfg = providers["anthropic"]
        openrouter_cfg = providers["openrouter"]

        console.print()
        console.print(f"  Extraction model: [bold]{obs.extraction_model}[/bold]")
        console.print(f"  Summary model:    [bold]{obs.summary_model}[/bold]")
        console.print(f"  Mode:             [bold]{obs.mode}[/bold]")
        console.print()
        console.print("  [dim]Provider env var names:[/dim]")
        console.print(f"    OpenAI API key:      [bold]{openai_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    OpenAI base URL:     [bold]{openai_cfg.base_url_env or '(not set)'}[/bold]")
        console.print(f"    Anthropic API key:   [bold]{anthropic_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    Anthropic base URL:  [bold]{anthropic_cfg.base_url_env or '(not set)'}[/bold]")
        console.print(f"    OpenRouter API key:  [bold]{openrouter_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    OpenRouter base URL: [bold]{openrouter_cfg.base_url_env or '(not set)'}[/bold]")

        action = questionary.select(
            "Observer:",
            choices=[
                "Set extraction model",
                "Set summary model",
                "Toggle mode",
                "Configure providers",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "Set extraction model":
            model = questionary.text("Extraction model (provider:model_id):", default=obs.extraction_model).ask()
            if model:
                obs.extraction_model = model.strip()
                console.print(f"[green]✓[/green] Extraction model → [bold]{model.strip()}[/bold]")
        elif action == "Set summary model":
            model = questionary.text("Summary model (provider:model_id):", default=obs.summary_model).ask()
            if model:
                obs.summary_model = model.strip()
                console.print(f"[green]✓[/green] Summary model → [bold]{model.strip()}[/bold]")
        elif action == "Toggle mode":
            new_mode = "off" if obs.mode == "on" else "on"
            obs.mode = new_mode
            console.print(f"[green]✓[/green] Mode → [bold]{new_mode}[/bold]")
        elif action == "Configure providers":
            _provider_config_menu()


def _provider_config_menu() -> None:
    """Provider configuration sub-menu for observer."""

    while True:
        obs = settings.observer
        providers = obs.provider_configs
        openai_cfg = providers["openai"]
        anthropic_cfg = providers["anthropic"]
        openrouter_cfg = providers["openrouter"]

        console.print()
        console.print("  [bold]OpenAI[/bold]")
        console.print(f"    API key env:  [bold]{openai_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    Base URL env: [bold]{openai_cfg.base_url_env or '(not set)'}[/bold]")
        console.print("  [bold]Anthropic[/bold]")
        console.print(f"    API key env:  [bold]{anthropic_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    Base URL env: [bold]{anthropic_cfg.base_url_env or '(not set)'}[/bold]")
        console.print("  [bold]OpenRouter[/bold]")
        console.print(f"    API key env:  [bold]{openrouter_cfg.api_key_env or '(not set)'}[/bold]")
        console.print(f"    Base URL env: [bold]{openrouter_cfg.base_url_env or '(not set)'}[/bold]")

        action = questionary.select(
            "Configure provider:",
            choices=[
                "OpenAI",
                "Anthropic",
                "OpenRouter",
                questionary.Separator(),
                "← Back",
            ],
        ).ask()

        if action is None or action == "← Back":
            return

        if action == "OpenAI":
            _configure_single_provider("openai", openai_cfg)
        elif action == "Anthropic":
            _configure_single_provider("anthropic", anthropic_cfg)
        elif action == "OpenRouter":
            _configure_single_provider("openrouter", openrouter_cfg)


def _configure_single_provider(provider_name: str, current: ProviderConfig) -> None:
    """Configure a single provider's env var names."""
    obs = settings.observer

    provider_label = _PROVIDER_LABELS.get(provider_name, provider_name)

    console.print(f"\n  [bold]{provider_label} Configuration[/bold]")
    console.print("  Enter environment variable names, not secret values. Leave empty to clear a value.")

    api_key = questionary.text(
        "API key env var name:",
        default=current.api_key_env or "",
    ).ask()
    if api_key is None:
        return

    base_url = questionary.text(
        "Base URL env var name (optional):",
        default=current.base_url_env or "",
    ).ask()
    if base_url is None:
        return

    new_api_key = api_key.strip() or None
    new_base_url = base_url.strip() or None

    obs.set_provider(provider_name, ProviderConfig(api_key_env=new_api_key, base_url_env=new_base_url))
    console.print(f"[green]✓[/green] {provider_label} provider updated.")
    if new_api_key:
        console.print(f"    API key env: [bold]{new_api_key}[/bold]")
    else:
        console.print("    API key env: [dim](cleared)[/dim]")
    if new_base_url:
        console.print(f"    Base URL env: [bold]{new_base_url}[/bold]")
    else:
        console.print("    Base URL env: [dim](cleared)[/dim]")
