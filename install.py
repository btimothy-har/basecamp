#!/usr/bin/env python3
# /// script
# dependencies = [
#   "questionary>=2.1.1",
#   "rich>=13.0",
# ]
# requires-python = ">=3.12"
# ///

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Final

import questionary
from rich.console import Console
from rich.panel import Panel

console = Console()

REPO_DIR: Final = Path(__file__).parent

MODULES: Final[list[tuple[str, Path, str]]] = [
    ("basecamp-core", REPO_DIR / "core", "basecamp"),
    ("basecamp-observer", REPO_DIR / "observer", "observer"),
]

EXTENSION_DIR: Final = REPO_DIR / "extension"


def save_install_dir(repo_dir: Path) -> None:
    config_file = Path.home() / ".basecamp" / "config.json"
    try:
        existing = json.loads(config_file.read_text()) if config_file.exists() else {}
        existing = existing if isinstance(existing, dict) else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    existing["install_dir"] = str(repo_dir)
    config_file.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    content = (json.dumps(existing, indent=2) + os.linesep).encode()
    fd, tmp_name = tempfile.mkstemp(dir=config_file.parent, suffix=".tmp")
    try:
        try:
            os.write(fd, content)
            os.fsync(fd)
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        os.replace(tmp_name, config_file)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    dir_fd = os.open(str(config_file.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)


def install_extension() -> None:
    """Install the pi extension: npm dependencies + register with pi."""
    npm = shutil.which("npm")
    if not npm:
        console.print("  [yellow]⚠[/yellow] npm not found — skipping extension install")
        return

    console.print("  Installing [bold]npm dependencies[/bold]...")
    result = subprocess.run(
        [npm, "install"],
        cwd=EXTENSION_DIR,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("\n[red]npm install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)

    pi = shutil.which("pi")
    if not pi:
        console.print("  [yellow]⚠[/yellow] pi not found — skipping extension registration")
        return

    console.print("  Registering [bold]extension[/bold] with pi...")
    result = subprocess.run(
        [pi, "install", str(EXTENSION_DIR)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("\n[red]pi install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def install_module(name: str, path: Path, cli: str, *, editable: bool) -> None:
    args = ["uv", "tool", "install", "--reinstall"]
    if editable:
        args.append("-e")
    args.append(str(path))

    console.print(f"  Installing [bold]{cli}[/bold] ({name})...")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"\n[red]Failed to install {name}:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up basecamp tools")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-e", "--editable", action="store_true", help="Install in editable mode")
    group.add_argument("--no-editable", action="store_true", help="Install in non-editable mode")
    args = parser.parse_args()

    editable: bool
    if args.editable:
        editable = True
    elif args.no_editable:
        editable = False
    else:
        answer = questionary.confirm("Install in editable mode?", default=True).ask()
        if answer is None:
            sys.exit(0)  # cancelled
        editable = answer

    console.print()
    console.print(Panel.fit("basecamp setup", style="bold blue"))
    console.print()

    for name, path, cli in MODULES:
        install_module(name, path, cli, editable=editable)

    console.print()
    console.print("[bold]pi extension[/bold]")
    console.print()
    install_extension()

    save_install_dir(REPO_DIR)

    console.print()
    console.print("[green]✓[/green] Done.")
    console.print()
    console.print(
        "If [bold]basecamp[/bold], [bold]observer[/bold], or [bold]recall[/bold]"
        " aren't found, add uv's tool bin to your PATH:",
    )
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')


if __name__ == "__main__":
    main()
