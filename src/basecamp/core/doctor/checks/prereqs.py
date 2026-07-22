"""Environment checks: required executables on the PATH and daemon runtime hygiene.

The executable list is the same one ``basecamp setup`` preflights, sourced from
:mod:`basecamp.core.prereqs` so the two never drift. The daemon check is
best-effort and emits nothing when the hub is running or was never started — it
only flags a *stale*
pid file (a crashed daemon's leftover), which the daemon itself recreates on its
next launch.
"""

from __future__ import annotations

from basecamp.core import prereqs as prereqs_module
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.doctor.liveness import pid_alive
from basecamp.core.doctor.locations import Locations

GROUP = "Prerequisites"


def check_prereqs(locations: Locations) -> list[Finding]:
    """Check required executables plus daemon runtime hygiene."""
    findings: list[Finding] = []
    for prereq in prereqs_module.PREREQUISITES:
        if prereqs_module.is_available(prereq.command):
            continue
        findings.append(Finding(GROUP, Severity.ERROR, f"{prereq.name} not found on PATH ({prereq.command})."))
    findings.extend(_check_daemon(locations))
    return findings


def _check_daemon(locations: Locations) -> list[Finding]:
    pidfile = locations.daemon_pidfile
    if not pidfile.exists():
        return []
    try:
        pid = int(pidfile.read_text().strip())
    except (OSError, ValueError):
        return [Finding(GROUP, Severity.WARNING, "hub daemon pid file is unreadable or corrupt.", detail=str(pidfile))]
    if pid_alive(pid):
        return []
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            "stale hub daemon pid file (the recorded process is not running).",
            remedy=Remedy.NONE,
            detail=f"{pidfile} → pid {pid}; the daemon recreates it on next launch.",
        )
    ]
