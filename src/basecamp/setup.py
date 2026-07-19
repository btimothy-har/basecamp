"""Setup command for basecamp — one-time environment bootstrap."""

import shutil
from pathlib import Path

from basecamp.claude.paths import claude_dir, shipped_prompts_dir
from basecamp.core.directories import to_home_relative
from basecamp.core.paths import USER_CONTEXT_DIR, USER_PROMPTS_DIR, USER_STYLES_DIR
from basecamp.core.projects import ProjectConfig, load_projects, save_projects
from basecamp.core.settings import settings
from basecamp.workspace.ui import console

_DOCTRINE_BEGIN = "<!-- BEGIN basecamp doctrine -->"
_DOCTRINE_END = "<!-- END basecamp doctrine -->"


def _check_prerequisite(name: str, command: str, hint: str | None = None) -> bool:
    """Check if a command is available on PATH."""
    found = shutil.which(command) is not None
    if found:
        console.print(f"  [green]✓[/green] {name}")
    else:
        console.print(f"  [red]✗[/red] {name} [dim]({command} not found on PATH)[/dim]")
        if hint:
            console.print(f"      [dim]{hint}[/dim]")
    return found


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


def _upsert_managed_block(existing: str, block: str) -> str:
    """Insert or replace the marked doctrine block, preserving all other content."""
    begin = existing.find(_DOCTRINE_BEGIN)
    end = existing.find(_DOCTRINE_END)
    if begin != -1 and end != -1 and end > begin:
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
    ok = True
    ok = _check_prerequisite("pi", "pi") and ok
    ok = _check_prerequisite("git", "git") and ok
    ok = (
        _check_prerequisite(
            "delta",
            "delta",
            hint="git-delta powers the companion diff viewer — brew install git-delta / cargo install git-delta",
        )
        and ok
    )
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

    console.print("[bold]Claude doctrine...[/bold]")
    _install_doctrine()
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
