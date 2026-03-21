"""Artifact domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy import cast, exists, func, or_
from sqlalchemy.orm import Session
from sqlalchemy.types import LargeBinary

from observer.data.enums import SectionType
from observer.data.schemas import ArtifactSchema
from observer.services.db import Database


class Artifact(BaseModel):
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

    def update_embedding(
        self,
        session: Session,
        *,
        embedding: list[float],
        content_hash: str,
        indexed_at: datetime,
    ) -> None:
        """Update embedding fields on this artifact row."""
        session.query(ArtifactSchema).filter(
            ArtifactSchema.id == self.id,
        ).update(
            {
                "embedding": embedding,
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

        Pending when: never indexed, updated since last index, or embedding is stale
        (content hash doesn't match current text). content_hash is only written by
        update_embedding(), so mismatch means the embedding hasn't caught up yet.
        """
        current_hash = func.encode(
            func.sha256(cast(ArtifactSchema.text, LargeBinary)),
            "hex",
        )
        return or_(
            ArtifactSchema.indexed_at.is_(None),
            ArtifactSchema.updated_at > ArtifactSchema.indexed_at,
            current_hash != ArtifactSchema.content_hash,
        )

    @classmethod
    def get_pending_index(cls) -> list[Self]:
        """Return artifacts that need (re-)indexing."""
        with Database().session() as session:
            rows = session.query(ArtifactSchema).filter(cls._pending_condition()).all()
            return [cls.model_validate(row) for row in rows]

    @classmethod
    def has_pending_index(cls) -> bool:
        """Check if any artifacts need (re-)indexing without loading rows."""
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
