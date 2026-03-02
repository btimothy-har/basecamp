"""Artifact domain model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from observer.data.enums import ArtifactSource, ArtifactType


class Artifact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    artifact_type: ArtifactType
    origin: ArtifactSource
    text: str
    transcript_id: int | None = None
    transcript_event_id: int | None = None
    prompt_event_id: int | None = None
    source: str | None = None
    created_at: datetime
