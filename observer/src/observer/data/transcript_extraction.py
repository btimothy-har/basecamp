"""TranscriptExtraction domain model."""

from __future__ import annotations

import hashlib
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
    embedding: list[float] | None = None
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None

    def save(self, session: Session) -> Self:
        """Upsert by (transcript_id, section_type). Updates text + updated_at if exists."""
        existing = (
            session.query(TranscriptExtractionSchema)
            .filter(
                TranscriptExtractionSchema.transcript_id == self.transcript_id,
                TranscriptExtractionSchema.section_type == self.section_type,
            )
            .first()
        )

        if existing is not None:
            existing.text = self.text
            existing.updated_at = self.updated_at
            session.flush()
            return type(self).model_validate(existing)

        row = TranscriptExtractionSchema(**self.model_dump())
        session.add(row)
        session.flush()
        return type(self).model_validate(row)

    def update_embedding(
        self,
        session: Session,
        *,
        embedding: list[float],
        content_hash: str,
        indexed_at: datetime,
    ) -> None:
        """Update embedding fields on this extraction row."""
        session.query(TranscriptExtractionSchema).filter(
            TranscriptExtractionSchema.id == self.id,
        ).update({
            "embedding": embedding,
            "content_hash": content_hash,
            "indexed_at": indexed_at,
        })

    @classmethod
    def get(cls, extraction_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(TranscriptExtractionSchema, extraction_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_pending_index(cls) -> list[Self]:
        """Return extractions that need (re-)indexing.

        Pending when: never indexed, updated since last index, or content hash mismatch.
        """
        with Database().session() as session:
            rows = session.query(TranscriptExtractionSchema).all()
            pending = []
            for row in rows:
                if row.indexed_at is None:
                    pending.append(cls.model_validate(row))
                elif row.updated_at > row.indexed_at:
                    pending.append(cls.model_validate(row))
                elif row.content_hash != hashlib.sha256(row.text.encode()).hexdigest():
                    pending.append(cls.model_validate(row))
            return pending

    @classmethod
    def get_for_transcript(cls, transcript_id: int) -> list[Self]:
        with Database().session() as session:
            rows = (
                session.query(TranscriptExtractionSchema)
                .filter(TranscriptExtractionSchema.transcript_id == transcript_id)
                .all()
            )
            return [cls.model_validate(row) for row in rows]

