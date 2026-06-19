"""Shared install logic for basecamp.

Called by both install.py (bootstrap) and `basecamp install` (reconfiguration).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import questionary
from basecamp_core.settings import settings
from rich.console import Console
from rich.panel import Panel

console = Console()

REPO_DIR: Final = Path(__file__).resolve().parents[2]

COMPONENT_STANDARD: Final = "standard"
COMPONENT_ENGINEERING: Final = "engineering"
COMPONENT_COMPANION: Final = "companion"
COMPONENT_SWARM: Final = "swarm"

_DEFAULT_COMPONENTS: Final = [
    COMPONENT_STANDARD,
    COMPONENT_ENGINEERING,
    COMPONENT_COMPANION,
    COMPONENT_SWARM,
]

_MANDATORY_TS_PACKAGE: Final = ("core/pi", "pi-core")
_TS_PACKAGE_ORDER: Final = [
    _MANDATORY_TS_PACKAGE,
    ("pi-ui", "pi-ui"),
    ("workspace/pi", "pi-workspace"),
    ("pi-tasks", "pi-tasks"),
    ("pi-git", "pi-git"),
    ("pi-engineering", "pi-engineering"),
    ("pi-companion/pi", "pi-companion"),
    ("pi-swarm/extension", "pi-swarm extension"),
]

_COMPONENT_TS_PACKAGES: Final = {
    COMPONENT_STANDARD: ["pi-ui", "workspace/pi", "pi-tasks", "pi-git"],
    COMPONENT_ENGINEERING: ["pi-engineering"],
    COMPONENT_COMPANION: ["pi-companion/pi"],
    COMPONENT_SWARM: ["pi-swarm/extension"],
}

_COMPONENT_DEPENDENCIES: Final = {
    COMPONENT_SWARM: ["pi-ui", "pi-tasks"],
}


@dataclass(frozen=True)
class InstallSelection:
    """Resolved Python extras and TypeScript packages for an install."""

    python_extra: str
    ts_packages: tuple[tuple[str, str], ...]


def resolve_install_selection(component_ids: list[str] | tuple[str, ...] | set[str]) -> InstallSelection:
    """Resolve selected optional components into installable artifacts.

    The core foundation is always included. Optional groups can add packages,
    and component dependencies are expanded without duplicating packages.
    """
    selected = set(component_ids)
    package_subpaths = {_MANDATORY_TS_PACKAGE[0]}

    for component_id in selected:
        package_subpaths.update(_COMPONENT_TS_PACKAGES.get(component_id, []))
        package_subpaths.update(_COMPONENT_DEPENDENCIES.get(component_id, []))

    ts_packages = tuple(package for package in _TS_PACKAGE_ORDER if package[0] in package_subpaths)
    python_extra = "[companion]" if COMPONENT_COMPANION in selected else ""
    return InstallSelection(python_extra=python_extra, ts_packages=ts_packages)


def _save_install_dir(repo_dir: Path) -> None:
    settings.install_dir = str(repo_dir)


def _install_pi_package(package_dir: Path, label: str) -> None:
    npm = shutil.which("npm")
    if not npm:
        console.print(f"  [yellow]⚠[/yellow] npm not found — skipping {label} install")
        return
    console.print(f"  Installing [bold]{label}[/bold] npm dependencies...")
    result = subprocess.run([npm, "install"], cwd=package_dir, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"\n[red]npm install failed for {label}:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)
    pi = shutil.which("pi")
    if not pi:
        console.print(f"  [yellow]⚠[/yellow] pi not found — skipping {label} registration")
        return
    console.print(f"  Registering [bold]{label}[/bold] with pi...")
    result = subprocess.run([pi, "install", str(package_dir)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"\n[red]pi install failed for {label}:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def _prompt_components() -> list[str]:
    console.print()
    console.print("[bold]Core foundation[/bold] (always installed): basecamp Python tool + pi-core")
    answer = questionary.checkbox(
        "Select optional components to install:",
        choices=[
            questionary.Choice(
                "Standard session capabilities (pi-ui, pi-workspace, pi-tasks, pi-git)",
                value=COMPONENT_STANDARD,
                checked=True,
            ),
            questionary.Choice("Engineering tools (pi-engineering)", value=COMPONENT_ENGINEERING, checked=True),
            questionary.Choice("Companion (Python extra + pi-companion)", value=COMPONENT_COMPANION, checked=True),
            questionary.Choice(
                "Swarm / async agents (pi-swarm; auto-includes pi-ui and pi-tasks)",
                value=COMPONENT_SWARM,
                checked=True,
            ),
        ],
        default=_DEFAULT_COMPONENTS,
    ).ask()
    if answer is None:
        sys.exit(0)
    return answer


def run_interactive_install(*, editable: bool | None = None) -> None:
    """Run the interactive basecamp install.

    Called by install.py (bootstrap) and `basecamp install` (reconfiguration).
    """
    if editable is None:
        answer = questionary.confirm("Install in editable mode?", default=True).ask()
        if answer is None:
            sys.exit(0)
        editable = answer

    component_ids = _prompt_components()
    selection = resolve_install_selection(component_ids)

    console.print()
    console.print(Panel.fit("basecamp setup", style="bold blue"))
    console.print()

    console.print("[bold]Python tool[/bold]")
    console.print()
    pkg_spec = f"{REPO_DIR}{selection.python_extra}"
    args = ["uv", "tool", "install", "--force", "--reinstall"]
    if editable:
        args.append("-e")
    args.append(pkg_spec)
    console.print("  Installing [bold]basecamp[/bold] Python tool...")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]Failed to install basecamp:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)

    console.print()
    console.print("[bold]Pi packages[/bold]")
    console.print()
    for subpath, label in selection.ts_packages:
        _install_pi_package(REPO_DIR / subpath, label)

    _save_install_dir(REPO_DIR)

    console.print()
    console.print("[green]✓[/green] Done.")
    console.print()
    console.print("If [bold]basecamp[/bold] isn't found, add uv's tool bin to your PATH:")
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')
