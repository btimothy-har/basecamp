"""``basecamp doctor`` orchestration: gather, report, then opt-in repair.

Repair is off unless a flag asks for it. ``--fix`` applies the lossless,
mechanical repairs silently; ``--clean`` reclaims provably-unused runtime after
an explicit per-item confirmation. When anything is applied the checks are
re-gathered so the closing summary and the exit code reflect the repaired state.
The exit code is non-zero only when an *error*-severity finding remains, so the
command is usable as a CI gate.
"""

from __future__ import annotations

import questionary

from basecamp.core.doctor import report
from basecamp.core.doctor.checks import gather
from basecamp.core.doctor.finding import Finding
from basecamp.core.doctor.locations import Locations
from basecamp.core.settings import Settings
from basecamp.core.settings import settings as default_settings

__all__ = ["run_doctor"]


def run_doctor(
    *,
    fix: bool = False,
    clean: bool = False,
    stale_days: int = 30,
    settings: Settings | None = None,
    locations: Locations | None = None,
) -> int:
    """Diagnose (and optionally repair) config and runtime; return the exit code."""
    active = settings or default_settings
    where = locations or Locations.default()

    findings = gather(active, where, stale_days)
    report.render_report(findings)

    applied = 0
    if fix:
        applied += _apply_fixes(findings)
    if clean:
        applied += _apply_cleans(findings)

    if applied:
        findings = gather(active, where, stale_days)

    report.render_summary(findings)
    return 1 if any(finding.is_error for finding in findings) else 0


def _apply_fixes(findings: list[Finding]) -> int:
    fixable = [finding for finding in findings if finding.is_fixable]
    if not fixable:
        return 0
    report.console.print("[bold]Applying fixes[/bold]")
    for finding in fixable:
        finding.apply()  # type: ignore[misc]  # is_fixable guarantees apply is set
        report.console.print(f"  [green]✓[/green] {finding.action or finding.summary}")
    report.console.print()
    return len(fixable)


def _apply_cleans(findings: list[Finding]) -> int:
    cleanable = [finding for finding in findings if finding.is_cleanable]
    if not cleanable:
        return 0
    report.console.print("[bold]Cleanup[/bold]")
    applied = 0
    for finding in cleanable:
        if finding.detail:
            report.console.print(f"  [dim]{finding.detail}[/dim]")
        if questionary.confirm(f"Reclaim: {finding.action}?", default=False).ask():
            finding.apply()  # type: ignore[misc]  # is_cleanable guarantees apply is set
            report.console.print(f"  [green]✓[/green] {finding.action}")
            applied += 1
        else:
            report.console.print("  [dim]skipped[/dim]")
    report.console.print()
    return applied
