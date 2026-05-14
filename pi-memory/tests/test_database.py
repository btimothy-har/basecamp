from pathlib import Path

import pytest
from pi_memory.db import (
    ActivityUnit,
    AnalysisRun,
    Base,
    Database,
    Episode,
    EpisodeManifest,
    Job,
    MemorySession,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from sqlalchemy import func, select, text


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_initialize_creates_parent_directory_and_database_file(tmp_path) -> None:
    db_path = tmp_path / "nested" / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()

        assert db_path.parent.is_dir()
        assert db_path.is_file()
    finally:
        database.close_if_open()


def test_sqlite_connections_enable_foreign_keys_and_wal(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()

        with database.engine.connect() as connection:
            foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
            journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

        assert foreign_keys == 1
        assert journal_mode == "wal"
    finally:
        database.close_if_open()


def test_configure_switches_to_isolated_database(tmp_path) -> None:
    first_path = tmp_path / "first" / "memory.db"
    second_path = tmp_path / "second" / "memory.db"
    database = Database(sqlite_url(first_path))

    try:
        database.initialize()
        first_engine = database.engine

        database.configure(sqlite_url(second_path))
        database.initialize()

        assert database.url == sqlite_url(second_path)
        assert database.engine is not first_engine
        assert first_path.is_file()
        assert second_path.is_file()
    finally:
        database.close_if_open()


def test_initialize_creates_transcript_entries_fts_projection(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()

        with database.engine.connect() as connection:
            create_sql = connection.execute(
                text(
                    """
                    SELECT sql
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'transcript_entries_fts'
                    """,
                ),
            ).scalar_one()

        assert "CREATE VIRTUAL TABLE" in create_sql.upper()
        assert "FTS5" in create_sql.upper()
        assert "search_text" in create_sql
    finally:
        database.close_if_open()


def test_transcript_entries_fts_projection_persists_after_reopen(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
    finally:
        database.close_if_open()

    reopened = Database(sqlite_url(db_path))
    try:
        with reopened.engine.connect() as connection:
            count = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'transcript_entries_fts'
                    """,
                ),
            ).scalar_one()

        assert count == 1
    finally:
        reopened.close_if_open()


def test_transcript_entries_fts_projection_uses_transcript_entry_rowid(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
            entry = TranscriptEntry(
                transcript=transcript,
                entry_type="message",
                raw_line='{"type":"message"}',
                byte_start=0,
                byte_end=18,
            )
            session.add(entry)
            session.flush()
            entry_id = entry.id
            session.execute(
                text(
                    """
                    INSERT INTO transcript_entries_fts(rowid, search_text)
                    VALUES (:rowid, :search_text)
                    """,
                ),
                {
                    "rowid": entry_id,
                    "search_text": "Derived projection text for nebula recall.",
                },
            )

        with database.engine.connect() as connection:
            rowids = (
                connection.execute(
                    text(
                        """
                    SELECT rowid
                    FROM transcript_entries_fts
                    WHERE transcript_entries_fts MATCH :query
                    """,
                    ),
                    {"query": "nebula"},
                )
                .scalars()
                .all()
            )

        assert rowids == [entry_id]
    finally:
        database.close_if_open()


def test_session_context_commits_and_closes(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        with database.session() as session:
            result = session.execute(text("SELECT 1")).scalar_one()

        assert result == 1
    finally:
        database.close_if_open()


class IntentionalRollbackError(Exception):
    """Raised by tests to exercise transaction rollback."""


def test_session_context_rolls_back_on_error(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        with pytest.raises(IntentionalRollbackError):
            with database.session() as session:
                session.add(MemorySession(session_id="pi-session-1"))
                raise IntentionalRollbackError()

        with database.session() as session:
            count = session.scalar(select(func.count()).select_from(MemorySession))

        assert count == 0
    finally:
        database.close_if_open()


def test_base_registers_schema_models() -> None:
    assert "sessions" in Base.metadata.tables
    assert "jobs" in Base.metadata.tables
    assert "analysis_runs" in Base.metadata.tables
    assert "activity_units" in Base.metadata.tables
    assert "episodes" in Base.metadata.tables
    assert "episode_manifests" in Base.metadata.tables
    assert "session_snapshot_shells" in Base.metadata.tables
    assert "transcript_entries_fts" not in Base.metadata.tables
    assert Job.__table__ is Base.metadata.tables["jobs"]
    assert AnalysisRun.__table__ is Base.metadata.tables["analysis_runs"]
    assert ActivityUnit.__table__ is Base.metadata.tables["activity_units"]
    assert Episode.__table__ is Base.metadata.tables["episodes"]
    assert EpisodeManifest.__table__ is Base.metadata.tables["episode_manifests"]
    assert SessionSnapshotShell.__table__ is Base.metadata.tables["session_snapshot_shells"]
