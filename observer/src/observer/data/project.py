"""Project domain model."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.data.schemas import ProjectSchema
from observer.data.transcript import Transcript
from observer.data.worktree import Worktree
from observer.services.db import Database


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    name: str
    repo_path: str
    worktrees: list[Worktree] = []
    transcripts: list[Transcript] = []

    def save(self, session: Session) -> Self:
        data = self.model_dump(exclude={"worktrees", "transcripts"})
        merged = session.merge(ProjectSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, project_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(ProjectSchema, project_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def get_by_repo_path(cls, repo_path: str) -> Self | None:
        with Database().session() as session:
            row = session.query(ProjectSchema).filter(ProjectSchema.repo_path == repo_path).first()
            return cls.model_validate(row) if row else None
