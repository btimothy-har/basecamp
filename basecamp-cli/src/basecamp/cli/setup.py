"""Setup command for basecamp — one-time environment bootstrap."""

import shutil
import subprocess

from basecamp.config import ProjectConfig, save_projects
from basecamp.config.directories import to_home_relative
from basecamp.constants import (
    SCRIPT_DIR,
    USER_CONTEXT_DIR,
    USER_STYLES_DIR,
)
from basecamp.settings import settings
from basecamp.ui import console

# The bundled memory stack (pi-total-recall) needs Node >= 24 (node:sqlite FTS5).
MIN_NODE_MAJOR = 24


def _check_prerequisite(name: str, command: str) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
    return found


def _node_major_version() -> int | None:
    """Best-effort Node major version on PATH; None if undetectable."""
    node = shutil.which("node")
    if not node:
        return None
    try:
        result = subprocess.run([node, "--version"], check=False, capture_output=True, text=True)
    except OSError:
        return None
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip().lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        return None


def _check_node_for_memory() -> None:
    """Soft check: the bundled memory stack needs Node >= 24. Never fails setup."""
    major = _node_major_version()
    if major is not None and major >= MIN_NODE_MAJOR:
        console.print(f"  [green]✓[/green] node >= {MIN_NODE_MAJOR} [dim](memory stack)[/dim]")
        return
    detected = "not found" if major is None else str(major)
    console.print(
        f"  [yellow]⚠[/yellow] node {detected} "
        f"[dim](memory stack pi-total-recall needs Node >= {MIN_NODE_MAJOR}; basecamp core works without it)[/dim]"
    )


def _scaffold_dirs() -> None:
    """Create user customization directories used by project config."""
    dirs = [
        USER_STYLES_DIR,
        USER_CONTEXT_DIR,
    ]
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)


def _create_default_config() -> None:
    """Create config.json with the basecamp project as a starting point."""
    relative_path = to_home_relative(SCRIPT_DIR)
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
    _check_node_for_memory()
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
    existing = settings.projects
    if existing:
        count = len(existing)
        console.print(f"  [green]✓[/green] {config_path} [dim]({count} project{'s' if count != 1 else ''})[/dim]")
    else:
        _create_default_config()
        console.print(f"  [green]✓[/green] Created {config_path} [dim](basecamp project)[/dim]")
    console.print()

    console.print("[green]✓[/green] Done. Review configuration with: [bold]basecamp config[/bold]")
    console.print("[dim]  Add your own projects from the Projects menu.[/dim]")
    console.print("[dim]  Memory (pi-total-recall) is bundled — see README → Memory for optional config.[/dim]")
    console.print()
