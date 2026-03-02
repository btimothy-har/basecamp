"""WorkItem domain model."""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.data.enums import WorkItemStage, WorkItemType
from observer.data.schemas import WorkItemSchema
from observer.services.db import Database


class WorkItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    transcript_id: int
    item_type: WorkItemType
    event_ids: list[int]
    processed: WorkItemStage = WorkItemStage.UNREFINED
    created_at: datetime

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        merged = session.merge(WorkItemSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, work_item_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(WorkItemSchema, work_item_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_by_processed(
        cls,
        processed: WorkItemStage,
        *,
        transcript_id: int | None = None,
        limit: int,
    ) -> list[Self]:
        with Database().session() as session:
            q = session.query(WorkItemSchema).filter(WorkItemSchema.processed == processed)
            if transcript_id is not None:
                q = q.filter(WorkItemSchema.transcript_id == transcript_id)
            rows = q.order_by(WorkItemSchema.created_at).limit(limit).all()
            return [cls.model_validate(r) for r in rows]

    @classmethod
    def has_by_processed(cls, processed: WorkItemStage) -> bool:
        with Database().session() as session:
            row = session.query(WorkItemSchema.id).filter(WorkItemSchema.processed == processed).limit(1).first()
            return row is not None

    @classmethod
    def get_unprocessed(cls, *, transcript_id: int | None = None, limit: int) -> list[Self]:
        return cls.get_by_processed(WorkItemStage.UNREFINED, transcript_id=transcript_id, limit=limit)

    @classmethod
    def has_unprocessed(cls) -> bool:
        return cls.has_by_processed(WorkItemStage.UNREFINED)
