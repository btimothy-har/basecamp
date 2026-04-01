"""Artifact domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy import or_
from sqlalchemy.orm import Session

from observer.data.enums import SectionType
from observer.data.schemas import ArtifactSchema
from observer.services.db import Database


class Artifact(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    transcript_id: int
    section_type: SectionType
    text: str
    content_hash: str | None = None
    created_at: datetime
    updated_at: datetime
    indexed_at: datetime | None = None

    def save(self, session: Session) -> Self:
        """Upsert by (transcript_id, section_type). Updates text + updated_at if exists."""
        existing = (
            session.query(ArtifactSchema)
            .filter(
                ArtifactSchema.transcript_id == self.transcript_id,
                ArtifactSchema.section_type == self.section_type,
            )
            .first()
        )

        if existing is not None:
            existing.text = self.text
            existing.updated_at = self.updated_at
            session.flush()
            return type(self).model_validate(existing)

        row = ArtifactSchema(**self.model_dump())
        session.add(row)
        session.flush()
        return type(self).model_validate(row)

    def update_index_metadata(
        self,
        session: Session,
        *,
        content_hash: str,
        indexed_at: datetime,
    ) -> None:
        """Update content_hash and indexed_at after ChromaDB indexing."""
        session.query(ArtifactSchema).filter(
            ArtifactSchema.id == self.id,
        ).update(
            {
                "content_hash": content_hash,
                "indexed_at": indexed_at,
            }
        )

    @classmethod
    def get(cls, artifact_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(ArtifactSchema, artifact_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def _pending_condition(cls):
        """SQLAlchemy filter expression for artifacts that need (re-)indexing.

        Pending when: never indexed, or updated since last index.
        Content hash comparison is done in Python after fetching.
        """
        return or_(
            ArtifactSchema.indexed_at.is_(None),
            ArtifactSchema.updated_at > ArtifactSchema.indexed_at,
        )

    @classmethod
    def get_pending_index(cls, *, transcript_id: int | None = None) -> list[Self]:
        """Return artifacts that need (re-)indexing."""
        with Database().session() as session:
            q = session.query(ArtifactSchema).filter(cls._pending_condition())
            if transcript_id is not None:
                q = q.filter(ArtifactSchema.transcript_id == transcript_id)
            rows = q.all()
            return [cls.model_validate(row) for row in rows]

    @classmethod
    def has_pending_index(cls) -> bool:
        """Check if any artifacts need (re-)indexing without loading rows."""
        from sqlalchemy import exists  # noqa: PLC0415

        with Database().session() as session:
            return session.query(exists().where(cls._pending_condition())).scalar()

    @staticmethod
    def parse_title(summary_text: str | None) -> str | None:
        """Extract title from summary text (first line: '## {title}')."""
        if summary_text and summary_text.startswith("## "):
            return summary_text.split("\n", 1)[0].removeprefix("## ")
        return None

    @classmethod
    def get_for_transcript(cls, transcript_id: int) -> list[Self]:
        with Database().session() as session:
            rows = session.query(ArtifactSchema).filter(ArtifactSchema.transcript_id == transcript_id).all()
            return [cls.model_validate(row) for row in rows]
