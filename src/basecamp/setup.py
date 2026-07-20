"""Setup command for basecamp — one-time environment bootstrap."""

from pathlib import Path

from basecamp.core.directories import to_home_relative
from basecamp.core.paths import USER_CONTEXT_DIR, USER_PROMPTS_DIR, USER_STYLES_DIR
from basecamp.core.prereqs import PREREQUISITES, is_available
from basecamp.core.projects import ProjectConfig, load_projects, save_projects
from basecamp.core.settings import settings
from basecamp.workspace.ui import console


def _check_prerequisites() -> bool:
    """Report each prerequisite's availability; return True if all are present."""
    ok = True
    for prereq in PREREQUISITES:
        if is_available(prereq.command):
            console.print(f"  [green]✓[/green] {prereq.name}")
        else:
            console.print(f"  [red]✗[/red] {prereq.name} [dim]({prereq.command} not found on PATH)[/dim]")
            if prereq.hint:
                console.print(f"      [dim]{prereq.hint}[/dim]")
            ok = False
    return ok


def _scaffold_dirs() -> None:
    """Create user customization directories used by project config."""
    dirs = [
        USER_CONTEXT_DIR,
        USER_STYLES_DIR,
        USER_PROMPTS_DIR,
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
    """Create the workspace projects file with basecamp as a starting point."""
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
    ok = _check_prerequisites()
    if not ok:
        console.print()
        console.print("[red]Missing prerequisites. Install them and try again.[/red]")
        raise SystemExit(1)
    console.print()

    console.print("[bold]Scaffolding directories...[/bold]")
    _scaffold_dirs()
    console.print(f"  [green]✓[/green] {USER_CONTEXT_DIR}")
    console.print(f"  [green]✓[/green] {USER_STYLES_DIR}")
    console.print(f"  [green]✓[/green] {USER_PROMPTS_DIR}")
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

    console.print("[green]✓[/green] Done. Review projects with: [bold]basecamp config project[/bold]")
    console.print("[dim]  Add your own projects from the project menu.[/dim]")
    console.print()
