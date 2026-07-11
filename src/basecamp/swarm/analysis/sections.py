"""The analyzer's output contract: the three dashboard sections.

Self-contained (no dependency on the legacy ``companion`` package) so the daemon
owns its own analysis schema. Serialized ``by_alias=True`` (camelCase) into the
``analysis`` store's ``sections_json``. This shape is part of the analyzer seam
(§6) — expected to move with the analyzer rework — so it lives beside the
analyzer, not in the store.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

MAX_SECTION_ITEMS = 5


class AnalysisSections(BaseModel):
    """Advisory observer notes for the supervisor dashboard.

    - ``monitor``: what a supervisor should know now without reading the thread.
    - ``needs_capture``: decisions/preferences not yet in the formal task list.
    - ``checkpoints``: advisory verification points (assumptions, scope drift).
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    monitor: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    needs_capture: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    checkpoints: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)

    @field_validator("monitor", "needs_capture", "checkpoints", mode="before")
    @classmethod
    def _cap_items(cls, value: object) -> object:
        """Truncate over-long sections so the cap never hard-fails validation."""
        return value[:MAX_SECTION_ITEMS] if isinstance(value, list) else value
