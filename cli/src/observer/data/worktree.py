"""Worktree domain model."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.data.schemas import WorktreeSchema
from observer.services.db import Database


class Worktree(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    project_id: int
    label: str
    path: str
    branch: str

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        merged = session.merge(WorktreeSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, worktree_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(WorktreeSchema, worktree_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_by_project_and_label(cls, project_id: int, label: str) -> Self | None:
        with Database().session() as session:
            row = (
                session.query(WorktreeSchema)
                .filter(
                    WorktreeSchema.project_id == project_id,
                    WorktreeSchema.label == label,
                )
                .first()
            )
            return cls.model_validate(row) if row else None
