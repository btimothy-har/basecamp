"""Shared install logic for basecamp.

Called by both install.py (bootstrap) and `basecamp install` (reconfiguration).

Every install gets everything: the Python tool (with all extras) and the
single Pi extension registered from the repo root. The pre-consolidation
component picker is gone by design (docs/design/repo-consolidation.md §3).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import questionary
from basecamp_core.settings import settings
from rich.console import Console
from rich.panel import Panel

console = Console()

REPO_DIR: Final = Path(__file__).resolve().parents[2]

_PYTHON_EXTRAS: Final = "[companion,swarm]"

# Recorded in config.json for informational purposes until the metadata field
# is retired in phase 3 of the consolidation.
_MODULE_IDS: Final = (
    "core",
    "ui",
    "workspace",
    "tasks",
    "git",
    "bash-reviewer",
    "engineering",
    "browser",
    "companion",
    "swarm",
)

# Pre-consolidation Pi package registrations to clean up — each was its own
# `pi install` target before the single-extension layout.
_LEGACY_PACKAGE_SUBPATHS: Final = (
    "core/pi",
    "pi-ui",
    "workspace/pi",
    "pi-tasks",
    "pi-git",
    "pi-bash-reviewer",
    "pi-engineering",
    "pi-browser",
    "pi-companion/pi",
    "pi-swarm/extension",
)


def _uninstall_legacy_pi_packages(pi: str) -> None:
    """Remove stale per-package registrations from the pre-consolidation layout.

    Best-effort: entries that were never registered (or were already removed)
    are skipped silently.
    """
    removed = []
    for subpath in _LEGACY_PACKAGE_SUBPATHS:
        result = subprocess.run(
            [pi, "uninstall", str(REPO_DIR / subpath)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            removed.append(subpath)
    if removed:
        console.print(f"  Unregistered {len(removed)} legacy Pi package registration(s).")


def _install_pi_extension() -> None:
    npm = shutil.which("npm")
    if not npm:
        console.print("  [yellow]⚠[/yellow] npm not found — skipping extension install")
        return
    console.print("  Installing extension npm dependencies...")
    result = subprocess.run([npm, "install"], cwd=REPO_DIR, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]npm install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)
    pi = shutil.which("pi")
    if not pi:
        console.print("  [yellow]⚠[/yellow] pi not found — skipping registration")
        return
    _uninstall_legacy_pi_packages(pi)
    console.print("  Registering [bold]basecamp[/bold] with pi...")
    result = subprocess.run([pi, "install", str(REPO_DIR)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]pi install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def run_interactive_install(*, editable: bool | None = None) -> None:
    """Run the basecamp install.

    Called by install.py (bootstrap) and `basecamp install` (reconfiguration).
    """
    if editable is None:
        answer = questionary.confirm("Install in editable mode?", default=True).ask()
        if answer is None:
            sys.exit(0)
        editable = answer

    console.print()
    console.print(Panel.fit("basecamp setup", style="bold blue"))
    console.print()

    console.print("[bold]Python tool[/bold]")
    console.print()
    pkg_spec = f"{REPO_DIR}{_PYTHON_EXTRAS}"
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
    console.print("[bold]Pi extension[/bold]")
    console.print()
    _install_pi_extension()

    settings.set_install_metadata(install_dir=str(REPO_DIR), installed_modules=_MODULE_IDS)

    console.print()
    console.print("[green]✓[/green] Done.")
    console.print()
    console.print("If [bold]basecamp[/bold] isn't found, add uv's tool bin to your PATH:")
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')
