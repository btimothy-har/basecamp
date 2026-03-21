"""TranscriptEvent domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.data.enums import WorkItemType
from observer.data.schemas import TranscriptEventSchema
from observer.services.db import Database


class TranscriptEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    transcript_id: int
    work_item_id: int
    event_type: WorkItemType
    text: str
    created_at: datetime

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        merged = session.merge(TranscriptEventSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get_for_transcript(cls, transcript_id: int) -> list[Self]:
        with Database().session() as session:
            rows = (
                session.query(TranscriptEventSchema)
                .filter(TranscriptEventSchema.transcript_id == transcript_id)
                .order_by(TranscriptEventSchema.work_item_id, TranscriptEventSchema.id)
                .all()
            )
            return [cls.model_validate(r) for r in rows]
