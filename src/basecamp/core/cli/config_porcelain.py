"""Typed porcelain subgroups for ``basecamp config``.

Thin click wiring over the existing section logic: ``config project`` (rich,
interactive), ``config env``, and ``config alias`` (the write path Pi's
``/model`` TUI shells out to). All persistence goes through the same flock'd
``settings`` writer the generic plumbing uses.
"""

from __future__ import annotations

import sys

import questionary
import rich_click as click

from basecamp.core.cli.project import (
    execute_project_add,
    execute_project_edit,
    execute_project_list,
    execute_project_remove,
    run_project_menu,
)
from basecamp.core.exceptions import LauncherError
from basecamp.core.model_aliases import load_model_aliases, remove_alias, rename_alias, set_alias
from basecamp.workspace import EnvironmentConfig, remove_environment, set_environment
from basecamp.workspace.cli.environment import execute_environment_list, run_environments_menu
from basecamp.workspace.ui import console, err_console

# --- projects -----------------------------------------------------------------


@click.group("project", invoke_without_command=True)
@click.pass_context
def project_group(ctx: click.Context) -> None:
    """Manage configured projects (repo roots, styles, context)."""
    if ctx.invoked_subcommand is None:
        run_project_menu()


@project_group.command("list")
def project_list() -> None:
    """List configured projects."""
    execute_project_list()


@project_group.command("add")
def project_add() -> None:
    """Interactively add a project."""
    execute_project_add()


@project_group.command("edit")
@click.argument("name")
def project_edit(name: str) -> None:
    """Interactively edit a project."""
    execute_project_edit(name)


@project_group.command("remove")
@click.argument("name")
def project_remove(name: str) -> None:
    """Remove a project."""
    execute_project_remove(name)


# --- environments -------------------------------------------------------------


@click.group("env", invoke_without_command=True)
@click.pass_context
def env_group(ctx: click.Context) -> None:
    """Manage per-repo worktree setup environments."""
    if ctx.invoked_subcommand is None:
        run_environments_menu()


@env_group.command("list")
def env_list() -> None:
    """List configured environments."""
    execute_environment_list()


@env_group.command("set")
@click.argument("repo")
@click.argument("command")
def env_set(repo: str, command: str) -> None:
    """Set the setup command for a repo (org/name)."""
    set_environment(repo, EnvironmentConfig(setup=command))
    console.print(f"Environment set for [bold]{repo}[/bold].")


@env_group.command("remove")
@click.argument("repo")
def env_remove(repo: str) -> None:
    """Remove the environment for a repo."""
    remove_environment(repo)
    console.print(f"Environment removed for [bold]{repo}[/bold].")


# --- model aliases ------------------------------------------------------------


def run_alias_menu(exit_label: str = "Done") -> None:
    """Interactive model-alias menu (parity with project/env consoles)."""
    while True:
        _display_aliases()
        aliases = load_model_aliases()
        action = questionary.select(
            "Model aliases:",
            choices=["Set", "Remove", questionary.Separator(), exit_label],
        ).ask()
        if action is None or action == exit_label:
            return
        if action == "Set":
            alias = questionary.text("Alias:").ask()
            model = questionary.text("Model:").ask()
            if alias and model:
                try:
                    set_alias(alias, model)
                except LauncherError as exc:
                    err_console.print(f"[red]Error:[/red] {exc}")
        elif action == "Remove":
            if not aliases:
                console.print("[dim]No model aliases configured.[/dim]")
                continue
            name = questionary.select(
                "Remove which alias?",
                choices=[*sorted(aliases), questionary.Separator(), "← Back"],
            ).ask()
            if name and name != "← Back":
                remove_alias(name)


def _display_aliases() -> None:
    aliases = load_model_aliases()
    if not aliases:
        console.print("[dim]No model aliases configured.[/dim]")
        return
    for alias, model in sorted(aliases.items()):
        console.print(f"{alias} → {model}")


@click.group("alias", invoke_without_command=True)
@click.pass_context
def alias_group(ctx: click.Context) -> None:
    """Manage model aliases (the model_aliases section)."""
    if ctx.invoked_subcommand is None:
        run_alias_menu()


@alias_group.command("list")
def alias_list() -> None:
    """List configured model aliases."""
    _display_aliases()


@alias_group.command("set")
@click.argument("alias")
@click.argument("model")
def alias_set(alias: str, model: str) -> None:
    """Set (or overwrite) a model alias."""
    try:
        stored_alias, stored_model = set_alias(alias, model)
    except LauncherError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Set alias [bold]{stored_alias}[/bold] → {stored_model}.")


@alias_group.command("remove")
@click.argument("alias")
def alias_remove(alias: str) -> None:
    """Remove a model alias."""
    if remove_alias(alias):
        console.print(f"Removed alias [bold]{alias.strip()}[/bold].")
    else:
        console.print(f"[dim]No alias named {alias.strip()}.[/dim]")


@alias_group.command("rename")
@click.argument("old")
@click.argument("new")
def alias_rename(old: str, new: str) -> None:
    """Rename a model alias (atomic)."""
    try:
        renamed, model = rename_alias(old, new)
    except LauncherError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"Renamed alias to [bold]{renamed}[/bold] → {model}.")
