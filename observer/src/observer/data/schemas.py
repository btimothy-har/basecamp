"""SQLAlchemy ORM schemas for observer.

Three layers:
- Ingestion: ProjectSchema, WorktreeSchema, TranscriptSchema, RawEventSchema
- Pipeline: WorkItemSchema, TranscriptEventSchema
- Memory: ArtifactSchema (includes embedding + search index)
"""

from datetime import UTC, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from observer.data.enums import SectionType, WorkItemType
from observer.services.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProjectSchema(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    repo_path: Mapped[str] = mapped_column(String, unique=True, nullable=False)

    worktrees: Mapped[list["WorktreeSchema"]] = relationship(back_populates="project")
    transcripts: Mapped[list["TranscriptSchema"]] = relationship(back_populates="project")


class WorktreeSchema(Base):
    __tablename__ = "worktrees"
    __table_args__ = (UniqueConstraint("project_id", "label"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    branch: Mapped[str] = mapped_column(String, nullable=False)

    project: Mapped["ProjectSchema"] = relationship(back_populates="worktrees")
    transcripts: Mapped[list["TranscriptSchema"]] = relationship(back_populates="worktree")


class TranscriptSchema(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    worktree_id: Mapped[int | None] = mapped_column(ForeignKey("worktrees.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    path: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    cursor_offset: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped["ProjectSchema"] = relationship(back_populates="transcripts")
    worktree: Mapped["WorktreeSchema | None"] = relationship(back_populates="transcripts")
    raw_events: Mapped[list["RawEventSchema"]] = relationship(back_populates="transcript")


class RawEventSchema(Base):
    __tablename__ = "raw_events"
    __table_args__ = (
        Index("ix_raw_events_transcript_id", "transcript_id"),
        Index("ix_raw_events_processed", "processed"),
        Index("ix_raw_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_uuid: Mapped[str | None] = mapped_column(String, nullable=True)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    transcript: Mapped["TranscriptSchema"] = relationship(back_populates="raw_events")


class WorkItemSchema(Base):
    __tablename__ = "work_items"
    __table_args__ = (Index("ix_work_items_transcript_processed", "transcript_id", "processed"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(
        Enum(WorkItemType, native_enum=False, create_constraint=False), nullable=False
    )
    event_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    transcript: Mapped["TranscriptSchema"] = relationship()
    transcript_events: Mapped[list["TranscriptEventSchema"]] = relationship(back_populates="work_item")


class TranscriptEventSchema(Base):
    __tablename__ = "transcript_events"
    __table_args__ = (
        Index("ix_transcript_events_transcript_id", "transcript_id"),
        Index("ix_transcript_events_work_item_id", "work_item_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    work_item_id: Mapped[int] = mapped_column(ForeignKey("work_items.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(
        Enum(WorkItemType, native_enum=False, create_constraint=False), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    transcript: Mapped["TranscriptSchema"] = relationship()
    work_item: Mapped["WorkItemSchema"] = relationship(back_populates="transcript_events")


class ArtifactSchema(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        UniqueConstraint("transcript_id", "section_type"),
        Index("ix_artifacts_transcript_id", "transcript_id"),
        Index("ix_artifacts_section_type", "section_type"),
        Index(
            "ix_artifacts_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id"), nullable=False)
    section_type: Mapped[str] = mapped_column(
        Enum(SectionType, native_enum=False, create_constraint=False), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(384), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    transcript: Mapped["TranscriptSchema"] = relationship()
