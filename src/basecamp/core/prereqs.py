"""Executable prerequisites basecamp expects on the PATH.

``basecamp setup`` and ``basecamp doctor`` share this required list so their
preflight and ongoing health checks cannot drift.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Prerequisite:
    """One executable basecamp requires on the PATH."""

    name: str
    command: str


PREREQUISITES: tuple[Prerequisite, ...] = (
    Prerequisite("pi", "pi"),
    Prerequisite("git", "git"),
)


def is_available(command: str) -> bool:
    """Return whether ``command`` resolves to an executable on the PATH."""
    return shutil.which(command) is not None


def missing_prerequisites() -> list[Prerequisite]:
    """Return the prerequisites not currently resolvable on the PATH."""
    return [prereq for prereq in PREREQUISITES if not is_available(prereq.command)]
