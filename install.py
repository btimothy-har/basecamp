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

CLI_DIR: Final = REPO_DIR / "basecamp-cli"
CORE_DIR: Final = REPO_DIR / "pi-core"

# Bundled memory stack. pi-session-search/pi-knowledge-search require Node >= 24
# (node:sqlite FTS5), so the install is gated on the Node major version.
MIN_NODE_MAJOR: Final = 24
PI_TOTAL_RECALL_SPEC: Final = "pi-total-recall@1.8.0"


def migrate_project_dirs(config: dict[str, object]) -> None:
    """Standalone copy of the settings migration; install.py runs before imports are reliable."""
    projects = config.get("projects")
    if not isinstance(projects, dict):
        return

    for project in projects.values():
        if not isinstance(project, dict) or "dirs" not in project:
            continue
        dirs = project["dirs"]
        has_repo_root = isinstance(project.get("repo_root"), str) and bool(project["repo_root"])
        has_additional_dirs = isinstance(project.get("additional_dirs"), list)
        if has_repo_root and has_additional_dirs:
            project.pop("dirs")
            continue
        if not isinstance(dirs, list) or not all(isinstance(item, str) for item in dirs):
            continue
        if not has_repo_root and not dirs:
            continue
        if not has_repo_root:
            project["repo_root"] = dirs[0]
        if not has_additional_dirs:
            project["additional_dirs"] = dirs[1:]
        project.pop("dirs")


def save_install_dir(repo_dir: Path) -> None:
    config_file = Path.home() / ".pi" / "basecamp" / "config.json"
    try:
        existing = json.loads(config_file.read_text()) if config_file.exists() else {}
        existing = existing if isinstance(existing, dict) else {}
    except (json.JSONDecodeError, OSError):
        existing = {}
    migrate_project_dirs(existing)
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


def install_pi_package(package_dir: Path, label: str) -> None:
    """Install a Pi package: npm dependencies + register with pi."""
    npm = shutil.which("npm")
    if not npm:
        console.print(f"  [yellow]⚠[/yellow] npm not found — skipping {label} install")
        return

    console.print(f"  Installing [bold]{label}[/bold] npm dependencies...")
    result = subprocess.run(
        [npm, "install"],
        cwd=package_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"\n[red]npm install failed for {label}:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)

    pi = shutil.which("pi")
    if not pi:
        console.print(f"  [yellow]⚠[/yellow] pi not found — skipping {label} registration")
        return

    console.print(f"  Registering [bold]{label}[/bold] with pi...")
    result = subprocess.run(
        [pi, "install", str(package_dir)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"\n[red]pi install failed for {label}:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def node_major_version() -> int | None:
    """Best-effort Node major version on PATH; None if undetectable."""
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


def install_pi_npm_package(spec: str, label: str) -> None:
    """Register a published Pi package with pi. Warns (not fatal) on failure."""
    pi = shutil.which("pi")
    if not pi:
        console.print(f"  [yellow]\u26a0[/yellow] pi not found \u2014 skipping {label} registration")
        return

    console.print(f"  Registering [bold]{label}[/bold] with pi...")
    result = subprocess.run(
        [pi, "install", f"npm:{spec}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print(f"  [yellow]\u26a0[/yellow] pi install failed for {label} \u2014 basecamp core is unaffected.")
        console.print(f"    [dim]{result.stderr.strip()}[/dim]")
        console.print(f"    [dim]Retry later with: pi install npm:{spec}[/dim]")


def install_memory_stack() -> None:
    """Install the bundled pi-total-recall memory stack, gated on Node >= 24."""
    major = node_major_version()
    if major is None:
        console.print(
            "  [yellow]\u26a0[/yellow] Could not determine Node version \u2014 skipping memory stack "
            f"({PI_TOTAL_RECALL_SPEC}). It requires Node >= {MIN_NODE_MAJOR}."
        )
        return
    if major < MIN_NODE_MAJOR:
        console.print(
            f"  [yellow]\u26a0[/yellow] Node {major} detected; memory stack ({PI_TOTAL_RECALL_SPEC}) "
            f"requires Node >= {MIN_NODE_MAJOR} \u2014 skipping."
        )
        console.print("    [dim]basecamp core is installed. Upgrade Node and re-run install.py to add memory.[/dim]")
        return
    install_pi_npm_package(PI_TOTAL_RECALL_SPEC, "pi-total-recall (memory stack)")


def install_python_tool(
    package_dir: Path,
    command_name: str,
    *,
    editable: bool,
) -> None:
    args = ["uv", "tool", "install", "--force", "--reinstall"]
    if editable:
        args.append("-e")
    args.append(str(package_dir))

    console.print(f"  Installing [bold]{command_name}[/bold] Python tool...")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"\n[red]Failed to install {command_name}:[/red]")
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

    console.print("[bold]Python tool[/bold]")
    console.print()
    install_python_tool(
        CLI_DIR,
        "basecamp",
        editable=editable,
    )

    console.print()
    console.print("[bold]Pi package[/bold]")
    console.print()
    install_pi_package(CORE_DIR, "pi-core")
    install_pi_package(REPO_DIR / "pi-ui", "pi-ui")
    install_pi_package(REPO_DIR / "pi-workspace", "pi-workspace")
    install_pi_package(REPO_DIR / "pi-tasks", "pi-tasks")
    install_pi_package(REPO_DIR / "pi-git", "pi-git")
    install_pi_package(REPO_DIR / "pi-engineering", "pi-engineering")
    install_pi_package(REPO_DIR / "pi-companion" / "pi", "pi-companion")
    install_pi_package(REPO_DIR / "pi-swarm" / "extension", "pi-swarm extension")
    install_memory_stack()

    # pi-swarm daemon CLI (bc-swarm) — optional async-agent runtime
    # TODO: uncomment when pi-swarm/cli is ready for standalone install
    # install_python_tool(REPO_DIR / "pi-swarm" / "cli", "bc-swarm", editable=editable)

    save_install_dir(REPO_DIR)

    console.print()
    console.print("[green]✓[/green] Done.")
    console.print()
    console.print(
        "If [bold]basecamp[/bold] isn't found, add uv's tool bin to your PATH:",
    )
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')


if __name__ == "__main__":
    main()
