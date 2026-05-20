"""Synchronous transcript ingest service for pi-memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pi_memory.db import Database, MemorySession, Observation, Transcript, TranscriptEntry, database
from pi_memory.transcripts import ParsedPiEntry, PiTranscriptParser


class TranscriptFileMissingError(FileNotFoundError):
    """Raised when an observe request references a missing transcript file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__(f"Transcript file does not exist: {path}")


@dataclass(frozen=True)
class ObserveInput:
    """Input for observing a Pi transcript file."""

    session_id: str
    transcript_path: Path | str
    cwd: str | None = None
    worktree_label: str | None = None
    worktree_path: str | None = None
    request_id: str | None = None
    request_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class IngestResult:
    """Result of a synchronous transcript observation."""

    session_id: str
    transcript_id: int
    observation_id: int
    entries_ingested: int
    cursor_offset: int
    file_size: int
    observed_at: datetime
    malformed_lines: int
    unsupported_lines: int


class TranscriptIngestService:
    """Synchronously ingest parsed Pi transcript entries into the database."""

    def __init__(self, database: Database = database, parser: PiTranscriptParser | None = None) -> None:
        self._database = database
        self._parser = PiTranscriptParser() if parser is None else parser

    def observe(self, request: ObserveInput) -> IngestResult:
        """Observe a transcript file and persist newly parsed entries.

        Args:
            request: Observe request containing session, transcript, and optional metadata.

        Returns:
            Summary of the persisted observation.

        Raises:
            TranscriptFileMissingError: If the transcript path is not an existing file.
        """
        transcript_path = Path(request.transcript_path).expanduser()
        if not transcript_path.is_file():
            raise TranscriptFileMissingError(transcript_path)

        self._database.initialize()
        transcript_cwd = self._parser.session_cwd(transcript_path)

        with self._database.session() as db_session:
            memory_session = _upsert_session(db_session, request, transcript_cwd=transcript_cwd)
            transcript = _upsert_transcript(db_session, memory_session.id, transcript_path)
            stored_cursor = transcript.cursor_offset or 0
            parsed = self._parser.parse(transcript_path, offset=stored_cursor)
            entries_ingested = _insert_new_entries(db_session, transcript.id, parsed.entries)

            transcript.cursor_offset = parsed.cursor_offset
            transcript.file_size = parsed.file_size
            _update_transcript_lineage(db_session, transcript, parsed.entries)
            _resolve_pending_child_transcripts(db_session, transcript)

            observed_at = datetime.now(UTC)
            observation = Observation(
                session_id=memory_session.id,
                transcript_id=transcript.id,
                observed_at=observed_at,
                request_id=request.request_id,
                request_metadata=request.request_metadata,
            )
            db_session.add(observation)
            db_session.flush()

            return IngestResult(
                session_id=memory_session.session_id,
                transcript_id=transcript.id,
                observation_id=observation.id,
                entries_ingested=entries_ingested,
                cursor_offset=transcript.cursor_offset,
                file_size=parsed.file_size,
                observed_at=observed_at,
                malformed_lines=parsed.malformed_lines,
                unsupported_lines=parsed.unsupported_lines,
            )


def _upsert_session(db_session: Session, request: ObserveInput, *, transcript_cwd: str | None) -> MemorySession:
    memory_session = db_session.scalar(select(MemorySession).where(MemorySession.session_id == request.session_id))
    if memory_session is None:
        memory_session = MemorySession(session_id=request.session_id)
        db_session.add(memory_session)

    effective_cwd = request.cwd if request.cwd is not None else transcript_cwd
    if effective_cwd is not None:
        memory_session.cwd = effective_cwd
    if request.worktree_label is not None:
        memory_session.worktree_label = request.worktree_label
    if request.worktree_path is not None:
        memory_session.worktree_path = request.worktree_path

    db_session.flush()
    return memory_session


def _upsert_transcript(db_session: Session, session_id: int, transcript_path: Path) -> Transcript:
    path = str(transcript_path)
    transcript = db_session.scalar(
        select(Transcript).where(Transcript.session_id == session_id, Transcript.path == path),
    )
    if transcript is None:
        transcript = Transcript(session_id=session_id, path=path, cursor_offset=0)
        db_session.add(transcript)
        db_session.flush()
    return transcript


def _update_transcript_lineage(
    db_session: Session,
    transcript: Transcript,
    entries: list[ParsedPiEntry],
) -> None:
    parent_path = _parsed_parent_transcript_path(entries)
    if parent_path is not None and parent_path != transcript.parent_transcript_path:
        transcript.parent_transcript_path = parent_path
        transcript.parent_transcript_id = None

    if transcript.parent_transcript_path is not None and transcript.parent_transcript_id is None:
        transcript.parent_transcript_id = _find_parent_transcript_id(db_session, transcript)


def _parsed_parent_transcript_path(entries: list[ParsedPiEntry]) -> str | None:
    for entry in entries:
        if entry.parent_session_path:
            return entry.parent_session_path
    return None


def _find_parent_transcript_id(db_session: Session, transcript: Transcript) -> int | None:
    if transcript.parent_transcript_path is None:
        return None

    return db_session.scalar(
        select(Transcript.id)
        .where(
            Transcript.path == transcript.parent_transcript_path,
            Transcript.id != transcript.id,
        )
        .order_by(Transcript.id)
        .limit(1),
    )


def _resolve_pending_child_transcripts(db_session: Session, transcript: Transcript) -> None:
    children = db_session.scalars(
        select(Transcript).where(
            Transcript.parent_transcript_path == transcript.path,
            Transcript.parent_transcript_id.is_(None),
            Transcript.id != transcript.id,
        ),
    )
    for child in children:
        child.parent_transcript_id = transcript.id


def _insert_new_entries(db_session: Session, transcript_id: int, entries: list[ParsedPiEntry]) -> int:
    if not entries:
        return 0

    existing_entry_ids, existing_spans = _existing_entry_keys(db_session, transcript_id, entries)
    inserted = 0

    for entry in entries:
        span = (entry.byte_start, entry.byte_end)
        if span in existing_spans or (entry.entry_id is not None and entry.entry_id in existing_entry_ids):
            continue

        try:
            with db_session.begin_nested():
                db_session.add(_transcript_entry(transcript_id, entry))
                db_session.flush()
        except IntegrityError:
            continue

        inserted += 1
        existing_spans.add(span)
        if entry.entry_id is not None:
            existing_entry_ids.add(entry.entry_id)

    return inserted


def _existing_entry_keys(
    db_session: Session,
    transcript_id: int,
    entries: list[ParsedPiEntry],
) -> tuple[set[str], set[tuple[int, int]]]:
    entry_ids = {entry.entry_id for entry in entries if entry.entry_id is not None}
    spans = {(entry.byte_start, entry.byte_end) for entry in entries}
    conditions = []
    if entry_ids:
        conditions.append(TranscriptEntry.entry_id.in_(entry_ids))
    if spans:
        conditions.append(tuple_(TranscriptEntry.byte_start, TranscriptEntry.byte_end).in_(spans))

    rows = db_session.execute(
        select(TranscriptEntry.entry_id, TranscriptEntry.byte_start, TranscriptEntry.byte_end).where(
            TranscriptEntry.transcript_id == transcript_id,
            or_(*conditions),
        ),
    )

    existing_entry_ids: set[str] = set()
    existing_spans: set[tuple[int, int]] = set()
    for entry_id, byte_start, byte_end in rows:
        if entry_id is not None:
            existing_entry_ids.add(entry_id)
        existing_spans.add((byte_start, byte_end))
    return existing_entry_ids, existing_spans


def _transcript_entry(transcript_id: int, entry: ParsedPiEntry) -> TranscriptEntry:
    return TranscriptEntry(
        transcript_id=transcript_id,
        entry_id=entry.entry_id,
        parent_id=entry.parent_id,
        entry_type=entry.entry_type,
        message_role=entry.message_role,
        timestamp=entry.timestamp,
        raw_line=entry.raw_line,
        byte_start=entry.byte_start,
        byte_end=entry.byte_end,
    )
