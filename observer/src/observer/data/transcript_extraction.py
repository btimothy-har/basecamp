"""TranscriptExtraction domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.data.enums import SectionType
from observer.data.schemas import TranscriptExtractionSchema
from observer.services.db import Database


class TranscriptExtraction(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    transcript_id: int
    section_type: SectionType
    text: str
    created_at: datetime

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        merged = session.merge(TranscriptExtractionSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, extraction_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(TranscriptExtractionSchema, extraction_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_for_transcript(cls, transcript_id: int) -> list[Self]:
        with Database().session() as session:
            rows = (
                session.query(TranscriptExtractionSchema)
                .filter(TranscriptExtractionSchema.transcript_id == transcript_id)
                .all()
            )
            return [cls.model_validate(row) for row in rows]

    @classmethod
    def delete_for_transcript(cls, transcript_id: int) -> None:
        """Delete all extractions for a transcript before re-extraction."""
        with Database().session() as session:
            session.query(TranscriptExtractionSchema).filter(
                TranscriptExtractionSchema.transcript_id == transcript_id
            ).delete()
