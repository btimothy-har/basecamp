"""``basecamp config`` — the single surface for the unified ``config.json``.

Two layers under one namespace:
  * generic plumbing — ``show/get/set/unset/edit`` on any dotted key, for
    machine use and writer-less sections like ``logseq``;
  * typed porcelain — ``project/env/alias`` (interactive/tabular), attached
    from :mod:`basecamp.config_cli.config_porcelain`.

Both go through the same flock'd writer and the same validation registry.
Bare ``basecamp config`` opens an interactive console over the sections.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

import questionary
import rich_click as click

from basecamp.config_cli.config_porcelain import alias_group, env_group, project_group, run_alias_menu
from basecamp.config_cli.project import run_project_menu
from basecamp.core.console import console, err_console
from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import settings
from basecamp.core.settings.document import edit_document, get_value, set_value, unset_value
from basecamp.workspace.cli.environment import run_environments_menu


def _guard(action: Callable[[], None]) -> None:
    """Run an action, reporting LauncherError as a clean CLI failure."""
    try:
        action()
    except LauncherError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)


@click.group("config", invoke_without_command=True)
@click.pass_context
def config(ctx: click.Context) -> None:
    """Inspect and edit basecamp configuration."""
    if ctx.invoked_subcommand is None:
        _run_console()


@config.command("show")
@click.argument("section", required=False)
def config_show(section: str | None) -> None:
    """Print the whole config.json, or one top-level section."""
    document = settings.read()
    console.print_json(data=document.get(section, {}) if section else document)


@config.command("get")
@click.argument("key")
def config_get(key: str) -> None:
    """Read a value at a dotted key (e.g. logseq.graph_dir).

    Keys split on '.', so a section/record name that itself contains a dot
    (e.g. a repo like org/next.js) can't be addressed here — use the porcelain
    (config project/env/alias) or `config edit`.
    """

    def run() -> None:
        value = get_value(key)
        if isinstance(value, dict | list):
            console.print_json(data=value)
        else:
            console.print(str(value))

    _guard(run)


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.option("--json", "as_json", is_flag=True, help="Parse VALUE as JSON (for null/lists/objects).")
def config_set(key: str, value: str, *, as_json: bool) -> None:
    """Set a dotted key to a scalar value (or raw JSON with --json).

    Keys split on '.', so for a section/record name containing a dot use the
    porcelain (config project/env/alias) or `config edit` instead.
    """

    def run() -> None:
        set_value(key, value, as_json=as_json)
        console.print(f"Set [bold]{key}[/bold].")

    _guard(run)


@config.command("unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Delete a dotted key."""

    def run() -> None:
        if unset_value(key):
            console.print(f"Unset [bold]{key}[/bold].")
        else:
            console.print(f"[dim]Key not set: {key}.[/dim]")

    _guard(run)


@config.command("edit")
def config_edit() -> None:
    """Open config.json in $EDITOR; validated on save."""

    def run() -> None:
        if edit_document():
            console.print("[green]✓[/green] Saved.")
        else:
            console.print("[dim]No changes.[/dim]")

    _guard(run)


config.add_command(project_group)
config.add_command(env_group)
config.add_command(alias_group)


def _run_console() -> None:
    """Interactive console: pick a section to manage, or edit the raw file."""
    while True:
        action = questionary.select(
            "basecamp config:",
            choices=[
                "Projects",
                "Environments",
                "Model aliases",
                "Edit raw config",
                questionary.Separator(),
                "Done",
            ],
        ).ask()

        if action is None or action == "Done":
            return
        if action == "Projects":
            run_project_menu("← Back")
        elif action == "Environments":
            run_environments_menu("← Back")
        elif action == "Model aliases":
            run_alias_menu("← Back")
        elif action == "Edit raw config":
            _edit_from_console()


def _edit_from_console() -> None:
    try:
        console.print("[green]✓[/green] Saved." if edit_document() else "[dim]No changes.[/dim]")
    except LauncherError as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
