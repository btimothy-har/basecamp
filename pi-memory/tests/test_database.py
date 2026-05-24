import sqlite3
from pathlib import Path

import pytest
from pi_memory.db.base import Base
from pi_memory.db.database import Database
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemoryRelation,
    DurableMemorySource,
    Episode,
    EpisodeManifest,
    Job,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from pi_memory.db.sqlite_migrations import CURRENT_SQLITE_SCHEMA_VERSION
from sqlalchemy import func, inspect, select, text


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def sqlite_user_version(database: Database) -> int:
    with database.engine.connect() as connection:
        return int(connection.execute(text("PRAGMA user_version")).scalar_one())


def index_by_name(database: Database, table_name: str, index_name: str) -> dict[str, object] | None:
    for index in inspect(database.engine).get_indexes(table_name):
        if index["name"] == index_name:
            return index
    return None


def create_old_style_memory_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id INTEGER NOT NULL,
                session_id VARCHAR NOT NULL,
                cwd VARCHAR,
                PRIMARY KEY (id),
                UNIQUE (session_id)
            );

            CREATE TABLE transcripts (
                id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                path VARCHAR NOT NULL,
                cursor_offset INTEGER DEFAULT 0 NOT NULL,
                file_size INTEGER,
                PRIMARY KEY (id),
                CONSTRAINT uq_transcripts_session_path UNIQUE (session_id, path),
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
            );

            CREATE INDEX ix_transcripts_session_cursor
            ON transcripts (session_id, cursor_offset);
            """,
        )


def create_old_style_activity_units_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id INTEGER NOT NULL,
                session_id VARCHAR NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (session_id)
            );

            CREATE TABLE transcripts (
                id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                path VARCHAR NOT NULL,
                parent_transcript_path VARCHAR,
                parent_transcript_id INTEGER,
                cursor_offset INTEGER DEFAULT 0 NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
            );

            CREATE TABLE analysis_runs (
                id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                transcript_id INTEGER NOT NULL,
                analysis_kind VARCHAR DEFAULT 'transcript_structure' NOT NULL,
                status VARCHAR DEFAULT 'completed' NOT NULL,
                analyzed_through_byte_offset INTEGER DEFAULT 0 NOT NULL,
                activity_count INTEGER DEFAULT 0 NOT NULL,
                episode_count INTEGER DEFAULT 0 NOT NULL,
                manifest_count INTEGER DEFAULT 0 NOT NULL,
                diagnostics_json JSON DEFAULT '{}' NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
                FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE
            );

            CREATE TABLE activity_units (
                id INTEGER NOT NULL,
                analysis_run_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                transcript_id INTEGER NOT NULL,
                episode_id INTEGER,
                ordinal INTEGER NOT NULL,
                kind VARCHAR NOT NULL,
                source_entry_ids_json JSON DEFAULT '[]' NOT NULL,
                byte_start INTEGER NOT NULL,
                byte_end INTEGER NOT NULL,
                raw_text_available BOOLEAN DEFAULT 1 NOT NULL,
                text_char_count INTEGER DEFAULT 0 NOT NULL,
                result_text_byte_count INTEGER DEFAULT 0 NOT NULL,
                result_text_line_count INTEGER DEFAULT 0 NOT NULL,
                receipt_json JSON DEFAULT '{}' NOT NULL,
                source_metadata_json JSON DEFAULT '{}' NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
                FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE
            );

            INSERT INTO sessions (id, session_id) VALUES (1, 'pi-session-1');
            INSERT INTO transcripts (id, session_id, path) VALUES (1, 1, '/tmp/pi/transcript.jsonl');
            INSERT INTO analysis_runs (id, session_id, transcript_id) VALUES (1, 1, 1);
            INSERT INTO activity_units (
                id,
                analysis_run_id,
                session_id,
                transcript_id,
                ordinal,
                kind,
                byte_start,
                byte_end
            ) VALUES (1, 1, 1, 1, 0, 'user_text', 0, 1);
            """,
        )


def create_old_style_episode_manifests_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (
                id INTEGER NOT NULL,
                session_id VARCHAR NOT NULL,
                PRIMARY KEY (id),
                UNIQUE (session_id)
            );

            CREATE TABLE transcripts (
                id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                path VARCHAR NOT NULL,
                parent_transcript_path VARCHAR,
                parent_transcript_id INTEGER,
                cursor_offset INTEGER DEFAULT 0 NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE
            );

            CREATE TABLE analysis_runs (
                id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                transcript_id INTEGER NOT NULL,
                analysis_kind VARCHAR DEFAULT 'transcript_structure' NOT NULL,
                status VARCHAR DEFAULT 'completed' NOT NULL,
                analyzed_through_byte_offset INTEGER DEFAULT 0 NOT NULL,
                activity_count INTEGER DEFAULT 0 NOT NULL,
                episode_count INTEGER DEFAULT 0 NOT NULL,
                manifest_count INTEGER DEFAULT 0 NOT NULL,
                diagnostics_json JSON DEFAULT '{}' NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
                FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE
            );

            CREATE TABLE episodes (
                id INTEGER NOT NULL,
                analysis_run_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                transcript_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                status VARCHAR DEFAULT 'closed' NOT NULL,
                close_reason VARCHAR DEFAULT 'transcript_end' NOT NULL,
                activity_count INTEGER DEFAULT 0 NOT NULL,
                message_count INTEGER DEFAULT 0 NOT NULL,
                tool_pair_count INTEGER DEFAULT 0 NOT NULL,
                byte_start INTEGER NOT NULL,
                byte_end INTEGER NOT NULL,
                boundary_metadata JSON DEFAULT '{}' NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
                FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE
            );

            CREATE TABLE episode_manifests (
                id INTEGER NOT NULL,
                analysis_run_id INTEGER NOT NULL,
                session_id INTEGER NOT NULL,
                transcript_id INTEGER NOT NULL,
                episode_id INTEGER NOT NULL,
                manifest_version INTEGER DEFAULT 1 NOT NULL,
                activity_count INTEGER DEFAULT 0 NOT NULL,
                tool_pair_count INTEGER DEFAULT 0 NOT NULL,
                first_entry_id INTEGER,
                last_entry_id INTEGER,
                byte_start INTEGER NOT NULL,
                byte_end INTEGER NOT NULL,
                activity_map_json JSON DEFAULT '{}' NOT NULL,
                source_spans_json JSON DEFAULT '[]' NOT NULL,
                omitted_raw_text_bytes INTEGER DEFAULT 0 NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(analysis_run_id) REFERENCES analysis_runs (id) ON DELETE CASCADE,
                FOREIGN KEY(session_id) REFERENCES sessions (id) ON DELETE CASCADE,
                FOREIGN KEY(transcript_id) REFERENCES transcripts (id) ON DELETE CASCADE,
                FOREIGN KEY(episode_id) REFERENCES episodes (id) ON DELETE CASCADE
            );

            INSERT INTO sessions (id, session_id) VALUES (1, 'pi-session-1');
            INSERT INTO transcripts (id, session_id, path) VALUES (1, 1, '/tmp/pi/transcript.jsonl');
            INSERT INTO analysis_runs (id, session_id, transcript_id) VALUES (1, 1, 1);
            INSERT INTO episodes (id, analysis_run_id, session_id, transcript_id, ordinal, byte_start, byte_end)
            VALUES (1, 1, 1, 1, 0, 0, 1);
            INSERT INTO episode_manifests (
                id,
                analysis_run_id,
                session_id,
                transcript_id,
                episode_id,
                byte_start,
                byte_end,
                omitted_raw_text_bytes
            ) VALUES (1, 1, 1, 1, 1, 0, 1, 42);
            """,
        )


def create_old_style_jobs_database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
                id INTEGER NOT NULL,
                kind VARCHAR NOT NULL,
                status VARCHAR DEFAULT 'queued' NOT NULL,
                payload_json JSON DEFAULT '{}' NOT NULL,
                priority INTEGER DEFAULT 0 NOT NULL,
                due_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                attempts INTEGER DEFAULT 0 NOT NULL,
                max_attempts INTEGER DEFAULT 3 NOT NULL,
                run_id VARCHAR,
                claimed_at DATETIME,
                claimed_by VARCHAR,
                started_at DATETIME,
                heartbeat_at DATETIME,
                lease_expires_at DATETIME,
                running_pid INTEGER,
                finished_at DATETIME,
                exit_code INTEGER,
                result_json JSON,
                last_error TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY (id)
            );

            INSERT INTO jobs (id, kind, payload_json) VALUES (1, 'interpret_session', '{}');
            """,
        )


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


def test_initialize_sets_current_sqlite_user_version(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        first_version = sqlite_user_version(database)
        database.initialize()

        assert first_version == CURRENT_SQLITE_SCHEMA_VERSION
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
    finally:
        database.close_if_open()


def test_initialize_creates_jobs_idempotency_schema(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("jobs")}
        index = index_by_name(database, "jobs", "uq_jobs_idempotency_key")

        assert "idempotency_key" in columns
        assert index is not None
        assert index["column_names"] == ["idempotency_key"]
        assert index["unique"]
    finally:
        database.close_if_open()


def test_initialize_upgrades_old_sqlite_jobs_with_idempotency_key(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_jobs_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("jobs")}
        index = index_by_name(database, "jobs", "uq_jobs_idempotency_key")

        assert "idempotency_key" in columns
        assert index is not None
        assert index["column_names"] == ["idempotency_key"]
        assert index["unique"]
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
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


def test_initialize_upgrades_old_sqlite_transcripts_with_lineage_columns(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_memory_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("transcripts")}
        indexes = {index["name"] for index in inspector.get_indexes("transcripts")}

        assert {"parent_transcript_path", "parent_transcript_id"}.issubset(columns)
        assert {
            "ix_transcripts_parent_transcript_id",
            "ix_transcripts_parent_transcript_path",
        }.issubset(indexes)
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
    finally:
        database.close_if_open()


def test_initialize_adds_phase_6_memory_tables_to_existing_sqlite_database(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_memory_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        table_names = set(inspector.get_table_names())

        assert {
            "durable_memory_items",
            "durable_memory_sources",
            "durable_memory_relations",
            "memory_projection_records",
            "durable_memory_audit_events",
        }.issubset(table_names)
        assert "sessions" in table_names
        assert "transcripts" in table_names
    finally:
        database.close_if_open()


def test_initialize_upgrades_old_sqlite_activity_units_with_source_origin(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_activity_units_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("activity_units")}
        indexes = {index["name"] for index in inspector.get_indexes("activity_units")}

        assert "source_origin" in columns
        assert "ix_activity_units_source_origin" in indexes
        with database.engine.connect() as connection:
            source_origin = connection.execute(
                text("SELECT source_origin FROM activity_units WHERE id = 1"),
            ).scalar_one()
        assert source_origin == "unknown"
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
    finally:
        database.close_if_open()


def test_initialize_upgrades_old_sqlite_activity_units_with_activity_text_columns(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_activity_units_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("activity_units")}
        indexes = {index["name"] for index in inspector.get_indexes("activity_units")}

        assert {
            "activity_text",
            "activity_text_kind",
            "activity_text_status",
            "activity_text_metadata_json",
        }.issubset(columns)
        assert "ix_activity_units_analysis_run_text_status" in indexes
        with database.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    SELECT activity_text, activity_text_kind, activity_text_status, activity_text_metadata_json
                    FROM activity_units
                    WHERE id = 1
                    """,
                ),
            ).one()

        assert row.activity_text is None
        assert row.activity_text_kind == "unavailable"
        assert row.activity_text_status == "pending"
        assert row.activity_text_metadata_json == "{}"
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
    finally:
        database.close_if_open()


def test_initialize_upgrades_old_sqlite_episode_manifests_with_tool_result_text_byte_count(
    tmp_path,
) -> None:
    db_path = tmp_path / "memory.db"
    create_old_style_episode_manifests_database(db_path)
    database = Database(sqlite_url(db_path))

    try:
        database.initialize()
        database.initialize()
        inspector = inspect(database.engine)
        columns = {column["name"] for column in inspector.get_columns("episode_manifests")}

        assert "tool_result_text_byte_count" in columns
        assert "omitted_raw_text_bytes" in columns
        with database.engine.connect() as connection:
            value = connection.execute(
                text("SELECT tool_result_text_byte_count FROM episode_manifests WHERE id = 1"),
            ).scalar_one()
        assert value == 42
        assert sqlite_user_version(database) == CURRENT_SQLITE_SCHEMA_VERSION
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
    assert "session_interpretation_snapshots" in Base.metadata.tables
    assert "session_interpretation_quality_reports" in Base.metadata.tables
    assert "durable_memory_items" in Base.metadata.tables
    assert "durable_memory_sources" in Base.metadata.tables
    assert "durable_memory_relations" in Base.metadata.tables
    assert "memory_projection_records" in Base.metadata.tables
    assert "durable_memory_audit_events" in Base.metadata.tables
    assert "transcript_entries_fts" not in Base.metadata.tables
    assert Job.__table__ is Base.metadata.tables["jobs"]
    assert AnalysisRun.__table__ is Base.metadata.tables["analysis_runs"]
    assert ActivityUnit.__table__ is Base.metadata.tables["activity_units"]
    assert Episode.__table__ is Base.metadata.tables["episodes"]
    assert EpisodeManifest.__table__ is Base.metadata.tables["episode_manifests"]
    assert SessionSnapshotShell.__table__ is Base.metadata.tables["session_snapshot_shells"]
    assert SessionInterpretationSnapshot.__table__ is Base.metadata.tables["session_interpretation_snapshots"]
    assert (
        SessionInterpretationQualityReport.__table__ is Base.metadata.tables["session_interpretation_quality_reports"]
    )
    assert DurableMemoryItem.__table__ is Base.metadata.tables["durable_memory_items"]
    assert DurableMemorySource.__table__ is Base.metadata.tables["durable_memory_sources"]
    assert DurableMemoryRelation.__table__ is Base.metadata.tables["durable_memory_relations"]
    assert MemoryProjectionRecord.__table__ is Base.metadata.tables["memory_projection_records"]
    assert DurableMemoryAuditEvent.__table__ is Base.metadata.tables["durable_memory_audit_events"]
