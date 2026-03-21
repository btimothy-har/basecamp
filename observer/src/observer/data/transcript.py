"""Transcript domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from observer.data.raw_event import RawEvent
from observer.data.schemas import TranscriptSchema
from observer.services.db import Database


class Transcript(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    project_id: int
    worktree_id: int | None = None
    session_id: str
    path: str
    cursor_offset: int = 0
    started_at: datetime
    ended_at: datetime | None = None
    raw_events: list[RawEvent] = Field(default_factory=list)

    def save(self, session: Session) -> Self:
        data = self.model_dump(exclude={"raw_events"})
        merged = session.merge(TranscriptSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, transcript_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(TranscriptSchema, transcript_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_active(cls) -> list[Self]:
        with Database().session() as session:
            rows = session.query(TranscriptSchema).filter(TranscriptSchema.ended_at.is_(None)).all()
            return [cls.model_validate(row) for row in rows]

    @classmethod
    def get_by_session_id(cls, session_id: str) -> Self | None:
        with Database().session() as session:
            row = session.query(TranscriptSchema).filter(TranscriptSchema.session_id == session_id).first()
            return cls.model_validate(row) if row else None
