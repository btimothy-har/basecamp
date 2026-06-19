"""Shared install logic for basecamp.

Called by both install.py (bootstrap) and `basecamp install` (reconfiguration).
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

MIN_NODE_MAJOR: Final = 24
PI_TOTAL_RECALL_SPEC: Final = "pi-total-recall@1.8.0"

_TS_PACKAGES: Final = [
    ("core/pi", "pi-core"),
    ("pi-ui", "pi-ui"),
    ("workspace/pi", "pi-workspace"),
    ("pi-tasks", "pi-tasks"),
    ("pi-git", "pi-git"),
    ("pi-engineering", "pi-engineering"),
    ("pi-companion/pi", "pi-companion"),
    ("pi-swarm/extension", "pi-swarm extension"),
]


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


def _node_major_version() -> int | None:
    node = shutil.which("node")
    if not node:
        return None
    result = subprocess.run([node, "--version"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip().lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        return None


def _install_pi_npm_package(spec: str, label: str) -> None:
    pi = shutil.which("pi")
    if not pi:
        console.print(f"  [yellow]⚠[/yellow] pi not found — skipping {label} registration")
        return
    console.print(f"  Registering [bold]{label}[/bold] with pi...")
    result = subprocess.run([pi, "install", f"npm:{spec}"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"  [yellow]⚠[/yellow] pi install failed for {label} — basecamp core is unaffected.")
        console.print(f"    [dim]{result.stderr.strip()}[/dim]")
        console.print(f"    [dim]Retry later with: pi install npm:{spec}[/dim]")


def _install_memory_stack() -> None:
    major = _node_major_version()
    if major is None:
        console.print(
            "  [yellow]⚠[/yellow] Could not determine Node version — skipping memory stack "
            f"({PI_TOTAL_RECALL_SPEC}). It requires Node >= {MIN_NODE_MAJOR}."
        )
        return
    if major < MIN_NODE_MAJOR:
        console.print(
            f"  [yellow]⚠[/yellow] Node {major} detected; memory stack ({PI_TOTAL_RECALL_SPEC}) "
            f"requires Node >= {MIN_NODE_MAJOR} — skipping."
        )
        console.print("    [dim]Upgrade Node and re-run basecamp install to add memory.[/dim]")
        return
    _install_pi_npm_package(PI_TOTAL_RECALL_SPEC, "pi-total-recall (memory stack)")


def run_interactive_install(*, editable: bool | None = None) -> None:
    """Run the interactive basecamp install.

    Called by install.py (bootstrap) and `basecamp install` (reconfiguration).
    """
    if editable is None:
        answer = questionary.confirm("Install in editable mode?", default=True).ask()
        if answer is None:
            sys.exit(0)
        editable = answer

    want_companion = questionary.confirm("Install companion (TUI + analyzer)?", default=True).ask()

    console.print()
    console.print(Panel.fit("basecamp setup", style="bold blue"))
    console.print()

    console.print("[bold]Python tool[/bold]")
    console.print()
    extra = "[companion]" if want_companion else ""
    pkg_spec = f"{REPO_DIR}{extra}"
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
    for subpath, label in _TS_PACKAGES:
        _install_pi_package(REPO_DIR / subpath, label)

    _install_memory_stack()

    _save_install_dir(REPO_DIR)

    console.print()
    console.print("[green]✓[/green] Done.")
    console.print()
    console.print("If [bold]basecamp[/bold] isn't found, add uv's tool bin to your PATH:")
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')
