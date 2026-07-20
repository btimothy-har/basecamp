"""Rich rendering for the doctor report: grouped findings, marks, and a summary.

Groups print in a fixed foundational-first order; a group with no findings shows
a single green line so the report always reflects the full check surface.
"""

from __future__ import annotations

from basecamp.core.console import console
from basecamp.core.doctor.finding import Finding

GROUP_ORDER = ("Config", "References", "Prerequisites", "Unused config", "Runtime")


def render_report(findings: list[Finding]) -> None:
    """Print the full grouped report."""
    console.print()
    console.print("[bold blue]basecamp doctor[/bold blue]")
    console.print()
    grouped: dict[str, list[Finding]] = {group: [] for group in GROUP_ORDER}
    for finding in findings:
        grouped.setdefault(finding.group, []).append(finding)
    for group in GROUP_ORDER:
        console.print(f"[bold]{group}[/bold]")
        items = grouped.get(group, [])
        if not items:
            console.print("  [green]✓[/green] no issues")
        for finding in items:
            _print_finding(finding)
        console.print()


def _print_finding(finding: Finding) -> None:
    mark = "[red]✗[/red]" if finding.is_error else "[yellow]⚠[/yellow]"
    console.print(f"  {mark} {finding.summary}")
    if finding.detail:
        console.print(f"      [dim]{finding.detail}[/dim]")
    if finding.is_fixable and finding.action:
        console.print(f"      [dim]fixable: {finding.action} — run with --fix[/dim]")
    elif finding.is_cleanable and finding.action:
        console.print(f"      [dim]reclaimable: {finding.action} — run with --clean[/dim]")


def render_summary(findings: list[Finding]) -> None:
    """Print the closing tally and the hints for the opt-in repair flags."""
    if not findings:
        console.print("[green]✓ All checks passed.[/green]")
        return
    errors = sum(1 for finding in findings if finding.is_error)
    warnings = len(findings) - errors
    parts: list[str] = []
    if errors:
        parts.append(f"[red]{errors} error{_s(errors)}[/red]")
    if warnings:
        parts.append(f"[yellow]{warnings} warning{_s(warnings)}[/yellow]")
    console.print("Summary: " + ", ".join(parts) + ".")
    fixable = sum(1 for finding in findings if finding.is_fixable)
    cleanable = sum(1 for finding in findings if finding.is_cleanable)
    if fixable:
        console.print(f"  [dim]{fixable} fixable — run[/dim] basecamp doctor --fix")
    if cleanable:
        console.print(f"  [dim]{cleanable} reclaimable — run[/dim] basecamp doctor --clean")


def _s(count: int) -> str:
    return "s" if count != 1 else ""
