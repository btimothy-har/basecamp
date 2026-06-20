"""Setup command for basecamp — one-time environment bootstrap."""

import shutil
from pathlib import Path

from basecamp_core.paths import USER_CONTEXT_DIR, USER_STYLES_DIR
from basecamp_core.settings import settings
from basecamp_workspace import ProjectConfig, load_projects, save_projects
from basecamp_workspace.directories import to_home_relative
from basecamp_workspace.ui import console


def _check_prerequisite(name: str, command: str) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
    return found


def _scaffold_dirs() -> None:
    """Create user customization directories used by project config."""
    dirs = [
        USER_STYLES_DIR,
        USER_CONTEXT_DIR,
    ]
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)


def _source_dir() -> Path:
    """Return the configured basecamp source directory, falling back to this checkout."""
    install_dir = settings.install_dir
    if install_dir:
        return Path(install_dir)
    return Path(__file__).resolve().parents[2]


def _create_default_config() -> None:
    """Create config.json with the basecamp project as a starting point."""
    relative_path = to_home_relative(_source_dir())
    save_projects(
        {
            "basecamp": ProjectConfig(
                repo_root=relative_path,
                description="Basecamp Source Code",
                working_style="engineering",
            )
        }
    )


def execute_setup() -> None:
    """Run the setup sequence: preflight, scaffold, default config."""
    console.print()
    console.print("[bold blue]basecamp setup[/bold blue]")
    console.print()

    console.print("[bold]Checking prerequisites...[/bold]")
    ok = True
    ok = _check_prerequisite("pi", "pi") and ok
    ok = _check_prerequisite("git", "git") and ok
    if not ok:
        console.print()
        console.print("[red]Missing prerequisites. Install them and try again.[/red]")
        raise SystemExit(1)
    console.print()

    console.print("[bold]Scaffolding directories...[/bold]")
    _scaffold_dirs()
    console.print(f"  [green]✓[/green] {USER_STYLES_DIR}")
    console.print(f"  [green]✓[/green] {USER_CONTEXT_DIR}")
    console.print()

    config_path = settings.path
    console.print("[bold]Project configuration...[/bold]")
    existing = load_projects()
    if existing:
        count = len(existing)
        console.print(f"  [green]✓[/green] {config_path} [dim]({count} project{'s' if count != 1 else ''})[/dim]")
    else:
        _create_default_config()
        console.print(f"  [green]✓[/green] Created {config_path} [dim](basecamp project)[/dim]")
    console.print()

    console.print("[green]✓[/green] Done. Review projects with: [bold]basecamp projects[/bold]")
    console.print("[dim]  Add your own projects from the project menu.[/dim]")
    console.print()
