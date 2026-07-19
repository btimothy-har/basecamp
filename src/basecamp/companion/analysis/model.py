"""Companion analysis model — the dashboard sections the UI renders.

The analyzer runs in the daemon now (see docs/design/companion-daemon-broker.md);
the UI parses the daemon's ``GET /analysis/{session_id}`` response into this model.
No sidecar file IO — the daemon owns analysis storage.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from basecamp.companion.snapshot import CompanionBaseModel

MAX_SECTION_ITEMS = 5


class AnalysisSections(CompanionBaseModel):
    """Shared dashboard section fields."""

    monitor: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    needs_capture: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    checkpoints: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)

    @field_validator("monitor", "needs_capture", "checkpoints", mode="before")
    @classmethod
    def _cap_items(cls, value: object) -> object:
        """Truncate over-long sections so the cap never hard-fails validation."""
        return value[:MAX_SECTION_ITEMS] if isinstance(value, list) else value


class CompanionAnalysis(AnalysisSections):
    """Dashboard analysis as returned by the daemon; metadata is optional."""

    model: str | None = None
    updated_at: str | None = None
    session_id: str | None = None
