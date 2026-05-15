"""Database engine and session management for pi-memory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.orm import Session, sessionmaker

from pi_memory.constants import MEMORY_DB_URL
from pi_memory.db.schema import SOURCE_ORIGIN_UNKNOWN, Base


class DatabaseSessionFactoryError(RuntimeError):
    """Raised when the database session factory cannot be initialized."""


class Database:
    """Manage the pi-memory SQLAlchemy engine and sessions."""

    def __init__(self, url: str = MEMORY_DB_URL) -> None:
        self._url = url
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    @property
    def url(self) -> str:
        """Return the configured database URL."""
        return self._url

    def configure(self, url: str) -> None:
        """Configure the database URL, closing any existing engine first."""
        if url == self._url and self._engine is None:
            return

        self.close_if_open()
        self._url = url

    def close_if_open(self) -> None:
        """Dispose the active engine, if one has been opened."""
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None

    @property
    def engine(self) -> Engine:
        """Return the lazily-created SQLAlchemy engine."""
        if self._engine is None:
            self._ensure_parent_directory()
            self._engine = self._create_engine(self._url)
            self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)
        return self._engine

    def initialize(self) -> None:
        """Create database parent directories and registered tables."""
        self._ensure_parent_directory()
        with self.engine.begin() as connection:
            Base.metadata.create_all(connection)
            if _is_sqlite_url(self._url):
                _upgrade_sqlite_transcript_lineage(connection)
                _upgrade_sqlite_activity_source_origin(connection)
                _upgrade_sqlite_episode_manifest_tool_result_text_byte_count(connection)
                connection.execute(
                    text(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS transcript_entries_fts
                        USING fts5(search_text)
                        """,
                    ),
                )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield a SQLAlchemy session scoped to a context manager."""
        _ = self.engine
        session_factory = self._session_factory
        if session_factory is None:
            raise DatabaseSessionFactoryError()

        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _create_engine(self, url: str) -> Engine:
        connect_args = {"check_same_thread": False} if _is_sqlite_url(url) else {}
        engine = create_engine(url, connect_args=connect_args)
        if _is_sqlite_url(url):
            _configure_sqlite(engine)
        return engine

    def _ensure_parent_directory(self) -> None:
        path = _sqlite_file_path(self._url)
        if path is not None:
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)


def _upgrade_sqlite_transcript_lineage(connection: Connection) -> None:
    """Add transcript lineage columns and indexes to existing SQLite databases."""
    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(transcripts)"))}
    if "parent_transcript_path" not in columns:
        connection.execute(text("ALTER TABLE transcripts ADD COLUMN parent_transcript_path VARCHAR"))
    if "parent_transcript_id" not in columns:
        connection.execute(
            text(
                """
                ALTER TABLE transcripts
                ADD COLUMN parent_transcript_id INTEGER REFERENCES transcripts(id) ON DELETE SET NULL
                """,
            ),
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_transcripts_parent_transcript_id ON transcripts (parent_transcript_id)"),
    )
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_transcripts_parent_transcript_path
            ON transcripts (parent_transcript_path)
            """,
        ),
    )


def _upgrade_sqlite_activity_source_origin(connection: Connection) -> None:
    """Add activity source-origin columns and indexes to existing SQLite databases."""
    if not _sqlite_table_exists(connection, "activity_units"):
        return

    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(activity_units)"))}
    if "source_origin" not in columns:
        connection.execute(
            text(
                f"""
                ALTER TABLE activity_units
                ADD COLUMN source_origin VARCHAR DEFAULT '{SOURCE_ORIGIN_UNKNOWN}' NOT NULL
                """,
            ),
        )

    connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_activity_units_source_origin ON activity_units (source_origin)"),
    )


def _upgrade_sqlite_episode_manifest_tool_result_text_byte_count(connection: Connection) -> None:
    """Add manifest tool-result text byte count to existing SQLite databases."""
    if not _sqlite_table_exists(connection, "episode_manifests"):
        return

    columns = {row[1] for row in connection.execute(text("PRAGMA table_info(episode_manifests)"))}
    if "tool_result_text_byte_count" not in columns:
        connection.execute(
            text(
                """
                ALTER TABLE episode_manifests
                ADD COLUMN tool_result_text_byte_count INTEGER DEFAULT 0 NOT NULL
                """,
            ),
        )
        if "omitted_raw_text_bytes" in columns:
            connection.execute(
                text(
                    """
                    UPDATE episode_manifests
                    SET tool_result_text_byte_count = omitted_raw_text_bytes
                    """,
                ),
            )


def _sqlite_table_exists(connection: Connection, table_name: str) -> bool:
    return (
        connection.execute(
            text(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = :table_name
                """,
            ),
            {"table_name": table_name},
        ).scalar_one_or_none()
        is not None
    )


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()


def _is_sqlite_url(url: str) -> bool:
    return make_url(url).drivername.startswith("sqlite")


def _sqlite_file_path(url: str) -> Path | None:
    parsed = make_url(url)
    if not parsed.drivername.startswith("sqlite"):
        return None
    if parsed.database in (None, "", ":memory:"):
        return None
    return Path(parsed.database).expanduser()


database = Database()
