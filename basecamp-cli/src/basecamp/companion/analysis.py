"""Companion analysis model and sidecar file helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from basecamp.companion.snapshot import CompanionBaseModel

COMPANION_ANALYSIS_VERSION = 1
MAX_SECTION_ITEMS = 5


class AnalysisSections(CompanionBaseModel):
    """Shared dashboard section fields."""

    recap: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    decisions: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    todos: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    deferred: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)
    warnings: list[str] = Field(default_factory=list, max_length=MAX_SECTION_ITEMS)

    @field_validator("recap", "decisions", "todos", "deferred", "warnings", mode="before")
    @classmethod
    def _cap_items(cls, value: object) -> object:
        """Truncate over-long sections so the cap never hard-fails validation."""
        return value[:MAX_SECTION_ITEMS] if isinstance(value, list) else value


class CompanionAnalysis(AnalysisSections):
    """Top-level companion analysis payload."""

    version: int
    session_id: str
    updated_at: str
    model: str | None = None


def companion_analysis_path(session_id: str, base_dir: Path | None = None) -> Path:
    """Return an analysis path for a session id."""

    resolved_base_dir = base_dir or (Path.home() / ".pi" / "companion")
    sanitized_session_id = re.sub(r"[^A-Za-z0-9_-]", "_", session_id)
    return resolved_base_dir / f"{sanitized_session_id}.analysis.json"


def load_analysis(path: Path) -> CompanionAnalysis | None:
    """Load an analysis file into a model, returning None on any failure."""

    try:
        raw_payload = path.read_text(encoding="utf-8")
        parsed_payload = json.loads(raw_payload)
        return CompanionAnalysis.model_validate(parsed_payload)
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def write_analysis(path: Path, analysis: CompanionAnalysis) -> None:
    """Atomically write an analysis model to disk in camelCase JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = Path(f"{path}.tmp")
    serialized = analysis.model_dump_json(by_alias=True, indent=2)
    temp_path.write_text(serialized, encoding="utf-8")
    os.replace(temp_path, path)
