from pathlib import Path

import pytest
from pi_memory.db import Database, MemorySession, Observation, Transcript, TranscriptEntry
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


def create_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/workspace")
        transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
        session.add(transcript)
        session.flush()
        return transcript.id


def test_initialize_creates_pi_transcript_schema_tables(database: Database) -> None:
    inspector = inspect(database.engine)

    assert {
        "sessions",
        "transcripts",
        "observations",
        "transcript_entries",
    }.issubset(inspector.get_table_names())


def test_session_identity_is_unique(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    MemorySession(session_id="pi-session-1"),
                    MemorySession(session_id="pi-session-1"),
                ],
            )


def test_transcript_path_is_unique_per_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add_all(
                [
                    Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl"),
                    Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl"),
                ],
            )


def test_transcript_requires_existing_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Transcript(session_id=12345, path="/tmp/pi/transcript.jsonl"))


def test_observation_requires_existing_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Observation(session_id=12345, request_id="request-1"))


def test_transcript_entry_prevents_duplicate_pi_entry_id(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_id="entry-1",
                        entry_type="message",
                        raw_line='{"id":"entry-1"}',
                        byte_start=0,
                        byte_end=16,
                    ),
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_id="entry-1",
                        entry_type="message",
                        raw_line='{"id":"entry-1"}',
                        byte_start=17,
                        byte_end=33,
                    ),
                ],
            )


def test_transcript_entry_prevents_duplicate_byte_span(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_type="message",
                        raw_line='{"type":"message"}',
                        byte_start=0,
                        byte_end=18,
                    ),
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_type="event",
                        raw_line='{"type":"event"}',
                        byte_start=0,
                        byte_end=18,
                    ),
                ],
            )


def test_transcript_entry_requires_positive_byte_span(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                TranscriptEntry(
                    transcript_id=transcript_id,
                    entry_type="message",
                    raw_line='{"type":"message"}',
                    byte_start=18,
                    byte_end=18,
                ),
            )


def test_transcript_entry_requires_existing_transcript(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                TranscriptEntry(
                    transcript_id=12345,
                    entry_type="message",
                    raw_line='{"type":"message"}',
                    byte_start=0,
                    byte_end=18,
                ),
            )
