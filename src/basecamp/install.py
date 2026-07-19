"""Install basecamp — the tool bootstrap plus the re-runnable wiring routine.

Two entry points, layered:

* ``run_bootstrap`` — the chicken-and-egg step. ``uv tool install`` the
  ``basecamp`` snapshot onto PATH and record the repo checkout as ``install_dir``
  (the value ``shipped_prompts_dir`` reads to find ``claude/prompts``). Only this
  step must run from the checkout, so it lives in the ``install.py`` bootstrap
  script / ``make install``. It ends by calling ``execute_install``.
* ``execute_install`` — everything else, all keyed off the recorded
  ``install_dir`` so it works from the installed tool too: register the plugin
  into Claude Code, install the home doctrine, scaffold the context dir, and seed
  the default project config. This is what ``basecamp install`` runs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

from basecamp.claude.paths import claude_dir, shipped_prompts_dir
from basecamp.claude.plugin import PluginRegistrationError, register_plugin
from basecamp.core.directories import to_home_relative
from basecamp.core.exceptions import LauncherError
from basecamp.core.paths import USER_CONTEXT_DIR
from basecamp.core.projects import ProjectConfig, load_projects, save_projects
from basecamp.core.settings import settings
from basecamp.workspace.ui import console

_DOCTRINE_BEGIN = "<!-- BEGIN basecamp doctrine -->"
_DOCTRINE_END = "<!-- END basecamp doctrine -->"

#: The repo checkout, resolved from this module. Correct only when running from
#: the checkout — i.e. the bootstrap path (``install.py`` / ``make install``).
REPO_DIR: Final = Path(__file__).resolve().parents[2]


def _check_prerequisite(name: str, command: str) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
    return found


def _scaffold_dirs() -> None:
    """Create the user context-override directory used by project config."""
    USER_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)


def _source_dir() -> Path:
    """Return the configured basecamp source directory, falling back to this checkout."""
    install_dir = settings.install_dir
    if install_dir:
        return Path(install_dir)
    return REPO_DIR


def _upsert_managed_block(existing: str, block: str) -> str:
    """Insert or replace the marked doctrine block, preserving all other content.

    Only splices when the markers form exactly one well-ordered pair; a desynced
    file (orphaned or duplicated markers) falls back to append so a marker mismatch
    can never delete user content between an orphan and an unrelated block.
    """
    begin = existing.find(_DOCTRINE_BEGIN)
    end = existing.find(_DOCTRINE_END)
    one_pair = existing.count(_DOCTRINE_BEGIN) == 1 and existing.count(_DOCTRINE_END) == 1
    if one_pair and begin != -1 and end > begin:
        end += len(_DOCTRINE_END)
        return existing[:begin] + block + existing[end:]
    if not existing.strip():
        return block + "\n"
    return existing.rstrip("\n") + "\n\n" + block + "\n"


def _install_doctrine() -> bool:
    """Write the shared doctrine into ``~/.claude/CLAUDE.md`` as a managed block."""
    source = shipped_prompts_dir() / "doctrine.md"
    if not source.exists():
        console.print(f"  [yellow]![/yellow] doctrine not found at {source} [dim](skipped)[/dim]")
        return False

    body = source.read_text(encoding="utf-8").strip("\n")
    block = f"{_DOCTRINE_BEGIN}\n{body}\n{_DOCTRINE_END}"

    dest = claude_dir() / "CLAUDE.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
    dest.write_text(_upsert_managed_block(existing, block), encoding="utf-8")
    console.print(f"  [green]✓[/green] {dest} [dim](basecamp doctrine block)[/dim]")
    return True


def _register_plugin() -> None:
    """Register + enable the plugin via the ``claude`` CLI (fail-soft).

    Drives ``claude plugin install`` (see :func:`register_plugin`) so a bare
    ``claude`` auto-loads the plugin. Fail-soft: a missing ``claude`` CLI or a
    failed command warns and skips rather than aborting the whole install.
    """
    install_dir = settings.install_dir
    if not install_dir:
        console.print(
            "  [yellow]![/yellow] install_dir not set [dim](run via install.py / make install first; skipped)[/dim]"
        )
        return
    try:
        register_plugin(Path(install_dir))
    except PluginRegistrationError as exc:
        console.print(f"  [yellow]![/yellow] plugin not registered: {exc} [dim](skipped)[/dim]")
        return
    console.print("  [green]✓[/green] plugin registered [dim](basecamp@basecamp enabled)[/dim]")


def _create_default_config() -> bool:
    """Seed the projects file with basecamp itself as a starting point.

    Returns ``True`` if seeded. A checkout outside ``$HOME`` can't be stored as a
    home-relative ``repo_root``, so we skip the convenience default (returning
    ``False``) rather than abort the whole install — the user can add projects from
    the menu.
    """
    try:
        relative_path = to_home_relative(_source_dir())
    except LauncherError:
        return False
    save_projects(
        {
            "basecamp": ProjectConfig(
                repo_root=relative_path,
                description="Basecamp Source Code",
            )
        }
    )
    return True


def execute_install() -> None:
    """Wire basecamp into the machine: plugin, doctrine, dirs, default config.

    Keyed off the recorded ``install_dir`` — safe to re-run from the installed
    ``basecamp install``.
    """
    console.print()
    console.print("[bold blue]basecamp install[/bold blue]")
    console.print()

    console.print("[bold]Checking prerequisites...[/bold]")
    if not _check_prerequisite("git", "git"):
        console.print()
        console.print("[red]Missing prerequisites. Install them and try again.[/red]")
        raise SystemExit(1)
    console.print()

    console.print("[bold]Scaffolding directories...[/bold]")
    _scaffold_dirs()
    console.print(f"  [green]✓[/green] {USER_CONTEXT_DIR}")
    console.print()

    console.print("[bold]Claude plugin...[/bold]")
    _register_plugin()
    console.print()

    console.print("[bold]Claude doctrine...[/bold]")
    _install_doctrine()
    console.print()

    config_path = settings.path
    console.print("[bold]Project configuration...[/bold]")
    existing = load_projects()
    if existing:
        count = len(existing)
        console.print(f"  [green]✓[/green] {config_path} [dim]({count} project{'s' if count != 1 else ''})[/dim]")
    elif _create_default_config():
        console.print(f"  [green]✓[/green] Created {config_path} [dim](basecamp project)[/dim]")
    else:
        console.print(
            f"  [yellow]![/yellow] {config_path} [dim](checkout outside $HOME; "
            "add projects with `basecamp config project`)[/dim]"
        )
    console.print()

    console.print("[green]✓[/green] Done. Review projects with: [bold]basecamp config project[/bold]")
    console.print("[dim]  Add your own projects from the project menu.[/dim]")
    console.print()


def run_bootstrap() -> None:
    """Install the ``basecamp`` tool onto PATH, then run ``execute_install``.

    The chicken-and-egg entry point, invoked from the ``install.py`` bootstrap
    script (``uv run install.py`` / ``make install``) from the repo checkout.
    """
    console.print()
    console.print("[bold blue]Installing basecamp[/bold blue]")
    console.print()

    console.print("  Installing the [bold]basecamp[/bold] Python tool...")
    result = subprocess.run(
        ["uv", "tool", "install", "--force", "--reinstall", str(REPO_DIR)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("\n[red]Failed to install basecamp:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)

    settings.set_install_metadata(install_dir=str(REPO_DIR))
    console.print("  [green]✓[/green] Installed on PATH.")
    console.print('  [dim]If `basecamp` isn\'t found: export PATH="$HOME/.local/bin:$PATH"[/dim]')

    execute_install()
