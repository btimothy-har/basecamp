"""Executable prerequisites basecamp expects on the PATH.

One definition, two consumers: ``basecamp setup`` (first-run preflight) and
``basecamp doctor`` (ongoing health) both check this list, so the two never
drift. ``essential`` distinguishes what basecamp cannot run without (``pi``,
``git``) from what only a subset of features needs (``delta``), which lets each
consumer choose an appropriate severity.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Prerequisite:
    """One executable basecamp relies on being resolvable on the PATH."""

    name: str
    command: str
    essential: bool
    hint: str | None = None


PREREQUISITES: tuple[Prerequisite, ...] = (
    Prerequisite("pi", "pi", essential=True),
    Prerequisite("git", "git", essential=True),
    Prerequisite(
        "delta",
        "delta",
        essential=False,
        hint="git-delta powers the companion diff viewer — brew install git-delta / cargo install git-delta",
    ),
)


def is_available(command: str) -> bool:
    """Return whether ``command`` resolves to an executable on the PATH."""
    return shutil.which(command) is not None


def missing_prerequisites() -> list[Prerequisite]:
    """Return the prerequisites not currently resolvable on the PATH."""
    return [prereq for prereq in PREREQUISITES if not is_available(prereq.command)]
