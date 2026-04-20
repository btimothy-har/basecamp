"""WorkItem domain model."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from observer.constants import REFINING_STALE_THRESHOLD
from observer.data.enums import WorkItemStage, WorkItemType
from observer.data.schemas import WorkItemSchema
from observer.services.db import Database

logger = logging.getLogger(__name__)


class WorkItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    transcript_id: int
    item_type: WorkItemType
    event_ids: list[int]
    processed: WorkItemStage = WorkItemStage.UNREFINED
    created_at: datetime
    claimed_at: datetime | None = None

    @field_validator("event_ids", mode="before")
    @classmethod
    def _deserialize_event_ids(cls, v: str | list[int]) -> list[int]:
        """Deserialize JSON string from SQLite back to list[int]."""
        if isinstance(v, str):
            return json.loads(v)
        return v

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        data["event_ids"] = json.dumps(data["event_ids"])
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
    ) -> list[Self]:
        with Database().session() as session:
            q = session.query(WorkItemSchema).filter(WorkItemSchema.processed == processed)
            if transcript_id is not None:
                q = q.filter(WorkItemSchema.transcript_id == transcript_id)
            rows = q.order_by(WorkItemSchema.created_at).all()
            return [cls.model_validate(r) for r in rows]

    @classmethod
    def has_by_processed(cls, processed: WorkItemStage) -> bool:
        with Database().session() as session:
            row = session.query(WorkItemSchema.id).filter(WorkItemSchema.processed == processed).limit(1).first()
            return row is not None

    @classmethod
    def get_unprocessed(cls, *, transcript_id: int | None = None) -> list[Self]:
        return cls.get_by_processed(WorkItemStage.UNREFINED, transcript_id=transcript_id)

    @classmethod
    def claim_unprocessed(cls, *, transcript_id: int | None = None) -> list[Self]:
        """Atomically claim UNREFINED rows by moving them to REFINING.

        Uses UPDATE...RETURNING to get the exact IDs transitioned, avoiding
        stale REFINING rows left by a previous crashed run. SQLite's
        file-level write lock ensures only one writer at a time.
        """
        with Database().session() as session:
            stmt = update(WorkItemSchema).where(WorkItemSchema.processed == WorkItemStage.UNREFINED)
            if transcript_id is not None:
                stmt = stmt.where(WorkItemSchema.transcript_id == transcript_id)
            stmt = stmt.values(
                processed=WorkItemStage.REFINING,
                claimed_at=datetime.now(UTC),
            ).returning(WorkItemSchema.id)
            claimed_ids = {row[0] for row in session.execute(stmt)}
            session.flush()

            if not claimed_ids:
                return []

            # Query by stage instead of IN(...) to avoid SQLite's 999 variable limit.
            # This is safe because SQLite's file-level write lock means we're the only
            # writer, so all REFINING rows in scope are ones we just claimed.
            q = session.query(WorkItemSchema).filter(WorkItemSchema.processed == WorkItemStage.REFINING)
            if transcript_id is not None:
                q = q.filter(WorkItemSchema.transcript_id == transcript_id)
            rows = q.order_by(WorkItemSchema.created_at).all()
            return [cls.model_validate(r) for r in rows if r.id in claimed_ids]

    @classmethod
    def has_unprocessed(cls) -> bool:
        return cls.has_by_processed(WorkItemStage.UNREFINED)

    @classmethod
    def recover_stale(cls, stale_threshold: int = REFINING_STALE_THRESHOLD) -> int:
        """Reset REFINING items older than the threshold back to UNREFINED.

        Handles both post-migration rows (stale claimed_at) and pre-migration
        rows (NULL claimed_at). Returns the number of items recovered.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=stale_threshold)
        with Database().session() as session:
            stmt = (
                update(WorkItemSchema)
                .where(WorkItemSchema.processed == WorkItemStage.REFINING)
                .where(
                    or_(
                        WorkItemSchema.claimed_at < cutoff,
                        WorkItemSchema.claimed_at.is_(None),
                    )
                )
                .values(processed=WorkItemStage.UNREFINED, claimed_at=None)
            )
            result = session.execute(stmt)
            count = result.rowcount
            if count:
                logger.warning("Recovered %d stale REFINING work items", count)
            return count
