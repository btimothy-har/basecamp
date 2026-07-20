"""The finding model shared across doctor checks, repair, and reporting.

A :class:`Finding` is one diagnosed problem. Clean checks emit nothing; every
finding names its ``group`` (for report layout), a ``severity`` (only errors
affect the exit code), and a ``remedy`` describing whether and how it can be
repaired. A finding that can repair itself carries an ``apply`` callable; the
run layer invokes it under ``--fix`` (lossless) or ``--clean`` (confirmed).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    """How serious a finding is. Only :attr:`ERROR` drives a non-zero exit."""

    ERROR = "error"
    WARNING = "warning"


class Remedy(str, Enum):
    """Whether a finding can be repaired, and under which posture."""

    NONE = "none"  # report-only: needs human judgement, never auto-applied
    FIX = "fix"  # lossless & mechanical, applied silently under --fix
    CLEAN = "clean"  # destructive, applied under --clean after confirmation


@dataclass
class Finding:
    """One diagnosed configuration or runtime problem."""

    group: str
    severity: Severity
    summary: str
    remedy: Remedy = Remedy.NONE
    detail: str | None = None
    action: str | None = None
    apply: Callable[[], None] | None = None

    @property
    def is_error(self) -> bool:
        """True when this finding should fail the run."""
        return self.severity is Severity.ERROR

    @property
    def is_fixable(self) -> bool:
        """True when ``--fix`` can apply a lossless repair for this finding."""
        return self.remedy is Remedy.FIX and self.apply is not None

    @property
    def is_cleanable(self) -> bool:
        """True when ``--clean`` can reclaim runtime for this finding (after confirmation)."""
        return self.remedy is Remedy.CLEAN and self.apply is not None
