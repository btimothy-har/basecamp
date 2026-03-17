"""Setup command for basecamp — one-time environment bootstrap."""

import shutil
from pathlib import Path

import questionary

from core.config import Config, ProjectConfig, save_config
from core.config.directories import to_home_relative
from core.constants import (
    OBSERVER_CONFIG,
    SCRIPT_DIR,
    USER_CONTEXT_DIR,
    USER_DIR,
    USER_PROMPTS_DIR,
    USER_WORKING_STYLES_DIR,
)
from core.exceptions import LauncherError
from core.settings import settings
from core.ui import console
from core.utils import is_observer_configured


def _check_prerequisite(name: str, command: str) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
    return found


def _scaffold_dirs() -> None:
    """Create the ~/.basecamp directory tree."""
    dirs = [
        USER_PROMPTS_DIR,
        USER_WORKING_STYLES_DIR,
        USER_CONTEXT_DIR,
    ]
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)


def _create_default_config() -> None:
    """Create config.json with the basecamp project as a starting point."""
    relative_path = to_home_relative(SCRIPT_DIR)
    config = Config(
        projects={
            "basecamp": ProjectConfig(
                dirs=[relative_path],
                description="Basecamp Source Code",
                working_style="engineering",
            )
        }
    )
    save_config(config)


def _setup_logseq() -> None:
    """Interactively configure Logseq graph integration."""
    existing_graph = settings.logseq_graph
    if existing_graph:
        console.print(f"  [green]✓[/green] logseq [dim](~/{existing_graph})[/dim]")
        return

    setup = questionary.confirm(
        "Set up Logseq integration? (enables basecamp log and basecamp reflect)",
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
    if is_observer_configured(OBSERVER_CONFIG):
        console.print("  [green]✓[/green] observer [dim](configured)[/dim]")
    else:
        console.print("  [yellow]![/yellow] observer [dim](not configured)[/dim]")
        console.print("    [dim]Install:[/dim] uv tool install -e ./observer && observer setup")
    console.print()

    # Logseq integration (optional)
    console.print("[bold]Logseq integration...[/bold]")
    _setup_logseq()
    console.print()

    console.print("[green]✓[/green] Done. Try editing the basecamp source: [bold]basecamp start basecamp[/bold]")
    console.print("[dim]  Add your own projects with:[/dim] [bold]basecamp project -h[/bold]")
    console.print()
