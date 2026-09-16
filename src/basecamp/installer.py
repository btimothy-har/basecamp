"""Shared install logic for basecamp.

Called by both install.py (bootstrap) and `basecamp install` (reconfiguration).

Every install gets everything: the Python tool and the single Pi extension
registered from the repo root. The pre-consolidation component picker and
extras are gone by design.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

from rich.panel import Panel

from basecamp.core.console import console
from basecamp.core.exceptions import LauncherError
from basecamp.core.settings import settings

REPO_DIR: Final = Path(__file__).resolve().parents[2]
OMP_PACKAGE: Final = "@oh-my-pi/pi-coding-agent"
OMP_USER_RULES: Final = (
    "ownership.md",
    "commit-checkpoints.md",
    "code-comments.md",
)
_COMMAND_TIMEOUT_SECONDS: Final = 10

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


def _uninstall_legacy_pi_packages(pi: str, repo_dir: Path) -> None:
    """Remove stale per-package registrations from the pre-consolidation layout.

    Best-effort: entries that were never registered (or were already removed)
    are skipped silently.
    """
    removed = []
    for subpath in _LEGACY_PACKAGE_SUBPATHS:
        result = subprocess.run(
            [pi, "uninstall", str(repo_dir / subpath)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            removed.append(subpath)
    if removed:
        console.print(f"  Unregistered {len(removed)} legacy Pi package registration(s).")


def _install_pi_extension(repo_dir: Path) -> None:
    npm = shutil.which("npm")
    if not npm:
        console.print("  [yellow]⚠[/yellow] npm not found — skipping extension install")
        return
    console.print("  Installing extension npm dependencies...")
    result = subprocess.run([npm, "install"], cwd=repo_dir, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]npm install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)
    pi = shutil.which("pi")
    if not pi:
        console.print("  [yellow]⚠[/yellow] pi not found — skipping registration")
        return
    _uninstall_legacy_pi_packages(pi, repo_dir)
    console.print("  Registering [bold]basecamp[/bold] with pi...")
    result = subprocess.run([pi, "install", str(repo_dir)], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]pi install failed:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)


def resolve_install_root(repo_dir: Path | None = None) -> Path:
    """Resolve the source checkout that owns installable Basecamp resources."""
    if repo_dir is not None:
        explicit = repo_dir.expanduser().resolve()
        if _is_basecamp_checkout(explicit):
            return explicit
        message = f"Basecamp source checkout not found at {explicit}."
        raise LauncherError(message)

    source = REPO_DIR.resolve()
    if _is_basecamp_checkout(source):
        return source
    if settings.install_dir:
        recorded = Path(settings.install_dir).expanduser().resolve()
        if _is_basecamp_checkout(recorded):
            return recorded
    message = "Basecamp source checkout not found; run install.py from a Basecamp clone."
    raise LauncherError(message)


def _is_basecamp_checkout(path: Path) -> bool:
    user_rules = path / "omp" / "user-rules"
    return (
        (path / "install.py").is_file()
        and (path / "package.json").is_file()
        and (path / "pyproject.toml").is_file()
        and (path / "src" / "basecamp" / "installer.py").is_file()
        and (path / "pi" / "extension.ts").is_file()
        and (path / "omp" / "package.json").is_file()
        and (path / "omp" / "extension.ts").is_file()
        and all((user_rules / name).is_file() for name in OMP_USER_RULES)
    )


def _ensure_omp() -> str:
    omp = shutil.which("omp")
    if omp is not None:
        _verify_omp(omp, existing=True)
        return omp

    bun = shutil.which("bun")
    if bun is None:
        console.print("\n[red]OMP is missing and Bun was not found.[/red]")
        console.print("Install Bun, then rerun basecamp install: https://bun.sh/docs/installation")
        raise SystemExit(1)

    console.print(f"  Installing [bold]{OMP_PACKAGE}[/bold] with Bun...")
    result = subprocess.run(
        [bun, "install", "-g", OMP_PACKAGE],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        console.print("\n[red]OMP installation failed:[/red]")
        console.print(result.stderr.strip())
        raise SystemExit(1)

    installed = shutil.which("omp")
    if installed is None:
        console.print("\n[red]OMP was installed but is not available on PATH.[/red]")
        console.print("Add Bun's global bin directory to PATH, then rerun basecamp install.")
        raise SystemExit(1)
    _verify_omp(installed, existing=False)
    return installed


def _verify_omp(omp: str, *, existing: bool) -> None:
    result = subprocess.run([omp, "--version"], check=False, capture_output=True, text=True)
    if result.returncode != 0:
        state = "existing" if existing else "installed"
        console.print(f"\n[red]The {state} OMP executable could not start:[/red]")
        console.print(result.stderr.strip() or f"exit status {result.returncode}")
        raise SystemExit(1)
    version = result.stdout.strip() or result.stderr.strip() or "version unknown"
    console.print(f"  Using OMP: {version}")


def _resolve_omp_agent_dir(omp: str, *, profile: str | None = None) -> Path:
    if profile is not None and not profile.strip():
        console.print("\n[red]OMP profile name cannot be empty.[/red]")
        raise SystemExit(1)
    command = [omp]
    if profile is not None:
        command.extend(("--profile", profile))
    command.extend(("config", "path"))
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        console.print("\n[red]Could not resolve OMP's user agent directory:[/red]")
        console.print(str(exc))
        raise SystemExit(1) from exc
    location = result.stdout.strip()
    if result.returncode != 0 or not location:
        console.print("\n[red]Could not resolve OMP's user agent directory:[/red]")
        console.print(result.stderr.strip() or f"exit status {result.returncode}")
        raise SystemExit(1)
    return Path(location).expanduser().resolve()


def _is_live_basecamp_rule_source(source: Path, name: str) -> bool:
    try:
        checkout = source.parents[2]
    except IndexError:
        return False
    expected = checkout / "omp" / "user-rules" / name
    return source == expected and _is_basecamp_checkout(checkout)


def _install_omp_user_rules(omp: str, repo_dir: Path, *, profile: str | None = None) -> None:
    source_dir = repo_dir / "omp" / "user-rules"
    sources = {name: (source_dir / name).resolve() for name in OMP_USER_RULES}
    missing = [source for source in sources.values() if not source.is_file()]
    if missing:
        console.print("\n[red]Basecamp user rule sources are missing:[/red]")
        for source in missing:
            console.print(f"  {source}")
        raise SystemExit(1)

    rules_dir = _resolve_omp_agent_dir(omp, profile=profile) / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)

    previous_root = settings.install_dir
    changes: list[tuple[Path, Path, bool]] = []
    for name, source in sources.items():
        destination = rules_dir / name
        managed_sources = {source}
        if isinstance(previous_root, str) and previous_root:
            managed_sources.add((Path(previous_root).expanduser() / "omp" / "user-rules" / name).resolve())

        if destination.is_symlink():
            link_target = (destination.parent / destination.readlink()).resolve()
            if link_target not in managed_sources and not _is_live_basecamp_rule_source(link_target, name):
                console.print(f"\n[red]Refusing to replace user-managed OMP rule:[/red] {destination}")
                raise SystemExit(1)
            if link_target != source:
                changes.append((destination, source, True))
        elif destination.exists():
            console.print(f"\n[red]Refusing to replace user-managed OMP rule:[/red] {destination}")
            raise SystemExit(1)
        else:
            changes.append((destination, source, False))

    for destination, source, replace in changes:
        if replace:
            destination.unlink()
        destination.symlink_to(source)

    console.print(f"  Linked {len(sources)} Basecamp rule(s) into {rules_dir}.")


def run_interactive_install(repo_dir: Path | None = None, *, profile: str | None = None) -> None:
    """Install Basecamp and its runtime prerequisites from one source checkout."""
    source_root = resolve_install_root(repo_dir)
    console.print()
    console.print(Panel.fit("basecamp install", style="bold blue"))
    console.print()

    console.print("[bold]Python tool[/bold]")
    console.print()
    args = ["uv", "tool", "install", "--force", "--reinstall", str(source_root)]
    console.print("  Installing [bold]basecamp[/bold] Python tool...")
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        console.print("\n[red]Failed to install basecamp:[/red]")
        console.print(result.stderr.strip())
        sys.exit(1)

    console.print()
    console.print("[bold]OMP runtime[/bold]")
    console.print()
    omp = _ensure_omp()

    console.print()
    console.print("[bold]OMP user rules[/bold]")
    console.print()
    _install_omp_user_rules(omp, source_root, profile=profile)

    console.print()
    console.print("[bold]Pi extension[/bold]")
    console.print()
    _install_pi_extension(source_root)

    settings.set_install_metadata(install_dir=str(source_root))

    console.print()
    console.print("[green]✓[/green] Installed.")
    console.print()
    console.print("If [bold]basecamp[/bold] isn't found, add uv's tool bin to your PATH:")
    console.print('  [dim]export PATH="$HOME/.local/bin:$PATH"[/dim]')
    console.print()
    console.print("Next, run [bold]basecamp setup[/bold] to scaffold your environment.")
