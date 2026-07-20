"""Command-line presentation for ``basecamp doctor``."""

from __future__ import annotations

from pathlib import Path

import rich_click as click

from basecamp.workspace.ui import console

from .models import DoctorCheck, DoctorPaths, DoctorReport, Severity
from .service import run_doctor

_STYLES: dict[Severity, tuple[str, str]] = {
    Severity.PASS: ("green", "✓"),
    Severity.INFO: ("blue", "•"),
    Severity.WARNING: ("yellow", "!"),
    Severity.REPAIRABLE: ("yellow", "↻"),
    Severity.ERROR: ("red", "✗"),
}


@click.command("doctor")
@click.option("--repair", is_flag=True, help="Apply backed-up config, layout, and Store repairs.")
def doctor(*, repair: bool) -> None:
    """Check Basecamp config, local-state layout, and hub database health."""
    report = run_doctor(DoctorPaths.for_home(Path.home()), repair=repair)
    render_report(report, repair=repair)
    if report.exit_code:
        raise click.exceptions.Exit(report.exit_code)


def render_report(report: DoctorReport, *, repair: bool) -> None:
    """Render a deterministic sectioned doctor report."""
    console.print()
    console.print("[bold blue]basecamp doctor[/bold blue]")
    console.print()

    sections: dict[str, list[DoctorCheck]] = {}
    for check in report.checks:
        sections.setdefault(check.section, []).append(check)
    for section, checks in sections.items():
        console.print(f"[bold]{section.replace('_', ' ').title()}[/bold]")
        for check in checks:
            _render_check(check)
    if report.archive_path is not None:
        console.print(f"\nRecovery archive: [bold]{report.archive_path}[/bold]")
    elif repair and report.repair_attempted:
        console.print("\n[dim]Repair pass completed.[/dim]")
    elif repair:
        console.print("\n[dim]No repairs were needed.[/dim]")

    if report.has_unresolved:
        console.print("\n[yellow]Doctor found unresolved issues.[/yellow]")
    else:
        console.print("\n[green]✓[/green] Basecamp local state is healthy.")


def _render_check(check: DoctorCheck) -> None:
    color, symbol = _STYLES[check.severity]
    location = f" [dim]({check.path})[/dim]" if check.path is not None else ""
    console.print(f"  [{color}]{symbol}[/{color}] {check.message}{location}")
