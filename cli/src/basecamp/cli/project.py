"""Interactive project management commands for basecamp."""

from __future__ import annotations

from pathlib import Path

import questionary

from basecamp.config import (
    ProjectConfig,
    load_projects,
    save_projects,
)
from basecamp.config.directories import to_home_relative
from basecamp.constants import SCRIPT_DIR, USER_CONTEXT_DIR, USER_STYLES_DIR
from basecamp.ui import console, display_projects


def _to_relative(path_str: str) -> str:
    """Convert an absolute path to home-relative for storage."""
    expanded = Path(path_str).expanduser().resolve()
    return to_home_relative(expanded)


def _available_styles() -> list[str]:
    """Scan extension + user dirs for available working styles."""
    styles: set[str] = set()
    ext_styles = SCRIPT_DIR / "pi-ext" / "system-prompts" / "styles"
    if ext_styles.exists():
        styles.update(p.stem for p in ext_styles.glob("*.md"))
    if USER_STYLES_DIR.exists():
        styles.update(p.stem for p in USER_STYLES_DIR.glob("*.md"))
    return sorted(styles)


def _available_contexts() -> list[str]:
    """Scan user dir for available context files."""
    if not USER_CONTEXT_DIR.exists():
        return []
    return sorted(p.stem for p in USER_CONTEXT_DIR.glob("*.md"))


def _prompt_directory(message: str, default: str = "~/") -> str | None:
    """Prompt for a directory path with validation."""
    result = questionary.path(
        message,
        default=default,
        only_directories=True,
    ).ask()
    if result is None:
        return None

    expanded = Path(result).expanduser().resolve()
    if not expanded.is_dir():
        console.print(f"  [red]Directory does not exist:[/red] {expanded}")
        return None
    return result


def _prompt_project_fields(
    existing_names: set[str],
) -> tuple[str, ProjectConfig] | None:
    """Walk through the interactive project creation flow.

    Returns (name, ProjectConfig) or None if the user cancelled.
    """
    name = questionary.text(
        "Project name:",
        validate=lambda val: (
            True if val.strip() and val.strip() not in existing_names else "Name is required and must be unique"
        ),
    ).ask()
    if name is None:
        return None
    name = name.strip()

    # Primary directory
    primary = _prompt_directory("Primary directory:")
    if primary is None:
        return None
    dirs = [_to_relative(primary)]

    # Additional directories
    while True:
        add_more = questionary.confirm(
            "Add another directory?",
            default=False,
        ).ask()
        if add_more is None:
            return None
        if not add_more:
            break
        extra = _prompt_directory("Additional directory:")
        if extra is None:
            return None
        dirs.append(_to_relative(extra))

    # Working style
    style_choices = ["none", *_available_styles()]
    working_style = questionary.select(
        "Working style:",
        choices=style_choices,
        default="none",
    ).ask()
    if working_style is None:
        return None
    if working_style == "none":
        working_style = None

    # Description
    description = questionary.text(
        "Description (optional):",
    ).ask()
    if description is None:
        return None

    # Context file (resolves to ~/.pi/context/{name}.md)
    context_files = _available_contexts()
    context: str | None = None
    if context_files:
        context_choices = ["none", *context_files]
        context = questionary.select(
            "Context file:",
            choices=context_choices,
            default="none",
        ).ask()
        if context is None:
            return None
        if context == "none":
            context = None
    else:
        console.print(f"  [dim]No context files found in {USER_CONTEXT_DIR}/[/dim]")

    project = ProjectConfig(
        dirs=dirs,
        description=description.strip(),
        working_style=working_style,
        context=context,
    )
    return name, project


def execute_project_list() -> None:
    """List all available projects."""
    projects = load_projects()
    display_projects(projects)


def execute_project_add() -> None:
    """Interactively add a new project."""
    projects = load_projects()
    existing_names = set(projects.keys())

    console.print()
    console.print("[bold blue]Add a new project[/bold blue]")
    console.print()

    result = _prompt_project_fields(existing_names=existing_names)
    if result is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    name, project = result
    projects[name] = project
    save_projects(projects)

    console.print(f"\n[green]✓[/green] Added project [bold]{name}[/bold]")


def _prompt_edit_fields(existing: ProjectConfig) -> ProjectConfig | None:
    """Walk through the interactive project editing flow.

    Returns updated ProjectConfig or None if the user cancelled.
    """
    # Primary directory
    dir_default = f"~/{existing.dirs[0]}" if existing.dirs else "~/"
    primary = _prompt_directory("Primary directory:", default=dir_default)
    if primary is None:
        return None
    dirs = [_to_relative(primary)]

    # Keep existing additional directories
    if len(existing.dirs) > 1:
        for d in existing.dirs[1:]:
            keep = questionary.confirm(
                f"Keep additional directory ~/{d}?",
                default=True,
            ).ask()
            if keep is None:
                return None
            if keep:
                dirs.append(d)

    # Add more directories
    while True:
        add_more = questionary.confirm(
            "Add another directory?",
            default=False,
        ).ask()
        if add_more is None:
            return None
        if not add_more:
            break
        extra = _prompt_directory("Additional directory:")
        if extra is None:
            return None
        dirs.append(_to_relative(extra))

    # Working style
    style_choices = ["none", *_available_styles()]
    style_default = existing.working_style if existing.working_style else "none"
    working_style = questionary.select(
        "Working style:",
        choices=style_choices,
        default=style_default,
    ).ask()
    if working_style is None:
        return None
    if working_style == "none":
        working_style = None

    # Description
    description = questionary.text(
        "Description (optional):",
        default=existing.description,
    ).ask()
    if description is None:
        return None

    # Context file (resolves to ~/.pi/context/{name}.md)
    context_files = _available_contexts()
    context: str | None = None
    if context_files:
        context_choices = ["none", *context_files]
        context_default = existing.context if existing.context else "none"
        context = questionary.select(
            "Context file:",
            choices=context_choices,
            default=context_default,
        ).ask()
        if context is None:
            return None
        if context == "none":
            context = None
    else:
        console.print(f"  [dim]No context files found in {USER_CONTEXT_DIR}/[/dim]")

    return ProjectConfig(
        dirs=dirs,
        description=description.strip(),
        working_style=working_style,
        context=context,
    )


_PROTECTED_PROJECT = "basecamp"


def execute_project_edit(name: str) -> None:
    """Interactively edit an existing project."""
    if name == _PROTECTED_PROJECT:
        console.print(f"[red]Error:[/red] The '{_PROTECTED_PROJECT}' project cannot be edited via CLI")
        raise SystemExit(1)

    projects = load_projects()
    if name not in projects:
        console.print(f"[red]Error:[/red] Project '{name}' not found")
        raise SystemExit(1)

    console.print()
    console.print(f"[bold blue]Edit project: {name}[/bold blue]")
    console.print()

    updated = _prompt_edit_fields(projects[name])
    if updated is None:
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    projects[name] = updated
    save_projects(projects)

    console.print(f"\n[green]✓[/green] Updated project [bold]{name}[/bold]")


def execute_project_remove(name: str) -> None:
    """Remove a project after confirmation."""
    if name == _PROTECTED_PROJECT:
        console.print(f"[red]Error:[/red] The '{_PROTECTED_PROJECT}' project cannot be removed via CLI")
        raise SystemExit(1)

    projects = load_projects()
    if name not in projects:
        console.print(f"[red]Error:[/red] Project '{name}' not found")
        raise SystemExit(1)

    confirmed = questionary.confirm(
        f"Remove project '{name}'?",
        default=False,
    ).ask()
    if not confirmed:
        console.print("[yellow]Cancelled.[/yellow]")
        return

    del projects[name]
    save_projects(projects)

    console.print(f"[green]✓[/green] Removed project [bold]{name}[/bold]")
