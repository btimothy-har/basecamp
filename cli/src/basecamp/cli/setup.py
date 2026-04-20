"""Setup command for basecamp — one-time environment bootstrap."""

import shutil
import zoneinfo
from pathlib import Path

import questionary

from basecamp.config import ProjectConfig, save_projects
from basecamp.config.directories import to_home_relative
from basecamp.constants import (
    SCRIPT_DIR,
    USER_AGENTS_DIR,
    USER_CONTEXT_DIR,
    USER_DIR,
    USER_LANGUAGES_DIR,
    USER_PROMPTS_DIR,
    USER_STYLES_DIR,
)
from basecamp.exceptions import LauncherError
from basecamp.settings import settings
from basecamp.ui import console


def _check_prerequisite(name: str, command: str) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
    return found


def _scaffold_dirs() -> None:
    """Create the ~/.pi/ resource directories."""
    dirs = [
        USER_PROMPTS_DIR,
        USER_STYLES_DIR,
        USER_LANGUAGES_DIR,
        USER_CONTEXT_DIR,
        USER_AGENTS_DIR,
    ]
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)


def _create_default_config() -> None:
    """Create config.json with the basecamp project as a starting point."""
    relative_path = to_home_relative(SCRIPT_DIR)
    save_projects(
        {
            "basecamp": ProjectConfig(
                dirs=[relative_path],
                description="Basecamp Source Code",
                working_style="engineering",
            )
        }
    )


def _setup_logseq() -> None:
    """Interactively configure Logseq graph integration."""
    existing_graph = settings.logseq_graph
    if existing_graph:
        tz_display = settings.timezone or "system local"
        console.print(f"  [green]✓[/green] logseq [dim](~/{existing_graph}, tz: {tz_display})[/dim]")
        reconfigure = questionary.confirm("  Reconfigure Logseq integration?", default=False).ask()
        if not reconfigure:
            return
    else:
        setup = questionary.confirm(
            "Set up Logseq integration? (enables basecamp log, reflect, and plan)",
            default=False,
        ).ask()
        if not setup:
            console.print("  [yellow]![/yellow] logseq [dim](skipped)[/dim]")
            return

    graph_path = questionary.path("Path to your Logseq graph:", only_directories=True).ask()
    if not graph_path:
        console.print("  [yellow]![/yellow] logseq [dim](skipped)[/dim]")
        return

    resolved = Path(graph_path).expanduser().resolve()
    if not resolved.is_dir():
        console.print(f"  [red]✗[/red] Directory not found: {resolved}")
        return

    try:
        settings.logseq_graph = to_home_relative(resolved)
    except LauncherError:
        console.print(f"  [red]✗[/red] Path must be under $HOME: {resolved}")
        return

    console.print(f"  [green]✓[/green] logseq [dim](~/{settings.logseq_graph})[/dim]")

    # Timezone for journal date boundaries
    tz_input = questionary.text(
        "Timezone for journal dates (IANA, e.g. America/Toronto):",
        default="",
    ).ask()
    if tz_input and tz_input.strip():
        tz_name = tz_input.strip()
        try:
            zoneinfo.ZoneInfo(tz_name)
            settings.timezone = tz_name
            console.print(f"  [green]✓[/green] timezone [dim]({tz_name})[/dim]")
        except (KeyError, zoneinfo.ZoneInfoNotFoundError):
            console.print(f"  [red]✗[/red] Unknown timezone: {tz_name} [dim](using system local)[/dim]")
    else:
        settings.timezone = None
        console.print("  [dim]  timezone: system local[/dim]")


def execute_setup() -> None:
    """Run the setup sequence: preflight, scaffold, default config."""
    console.print()
    console.print("[bold blue]basecamp setup[/bold blue]")
    console.print()

    # Pre-flight checks
    console.print("[bold]Checking prerequisites...[/bold]")
    ok = True
    ok = _check_prerequisite("claude CLI", "claude") and ok
    ok = _check_prerequisite("git", "git") and ok
    if not ok:
        console.print()
        console.print("[red]Missing prerequisites. Install them and try again.[/red]")
        raise SystemExit(1)

    # Optional: VS Code (needed for basecamp open)
    if not shutil.which("code"):
        console.print("  [yellow]![/yellow] VS Code CLI [dim](code not found — basecamp open will not work)[/dim]")
    console.print()

    # Scaffold directories
    console.print("[bold]Scaffolding directories...[/bold]")
    _scaffold_dirs()
    console.print(f"  [green]✓[/green] {USER_DIR}")
    console.print()

    # Project configuration
    config_path = settings.path
    console.print("[bold]Project configuration...[/bold]")
    existing = settings.projects
    if existing:
        count = len(existing)
        console.print(f"  [green]✓[/green] {config_path} [dim]({count} project{'s' if count != 1 else ''})[/dim]")
    else:
        _create_default_config()
        console.print(f"  [green]✓[/green] Created {config_path} [dim](basecamp project)[/dim]")
    console.print()

    # Optional modules
    console.print("[bold]Optional modules...[/bold]")
    if settings.observer.is_configured:
        console.print("  [green]✓[/green] observer [dim](configured)[/dim]")
    else:
        console.print("  [yellow]![/yellow] observer [dim](not configured — run `observer setup`)[/dim]")
    console.print()

    # Logseq integration (optional)
    console.print("[bold]Logseq integration...[/bold]")
    _setup_logseq()
    console.print()

    console.print("[green]✓[/green] Done. Try editing the basecamp source: [bold]basecamp claude basecamp[/bold]")
    console.print("[dim]  Add your own projects with:[/dim] [bold]basecamp project -h[/bold]")
    console.print()
