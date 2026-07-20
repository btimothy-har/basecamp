"""Aggregate every doctor check into a single ordered list of findings.

Integrity runs first: if ``config.json`` is absent (not set up) or corrupt, the
config-derived checks would run against a silently-empty document and report
nothing useful, so they are skipped and only the config-independent checks
(prereqs, runtime) run alongside that single blocking finding.
"""

from __future__ import annotations

from basecamp.core.doctor.checks import integrity, prereqs, references, runtime, unused
from basecamp.core.doctor.finding import Finding
from basecamp.core.doctor.locations import Locations
from basecamp.core.settings import Settings

__all__ = ["gather"]


def gather(settings: Settings, locations: Locations, stale_days: int) -> list[Finding]:
    """Run all checks and return their findings, most foundational group first."""
    document, blocker = integrity.raw_parse(settings)
    if blocker is not None:
        return [blocker, *prereqs.check_prereqs(locations), *runtime.check_runtime(locations, stale_days)]
    return [
        *integrity.check_version(document, settings),
        *integrity.check_sections(document),
        *references.check_references(settings, locations),
        *unused.check_unused(document, settings, locations),
        *prereqs.check_prereqs(locations),
        *runtime.check_runtime(locations, stale_days),
    ]
