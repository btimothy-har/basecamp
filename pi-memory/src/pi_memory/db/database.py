"""Database engine and session management for pi-memory."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from pi_memory.constants import MEMORY_DB_URL
from pi_memory.db.base import Base
from pi_memory.db.models import ensure_models_registered
from pi_memory.db.sqlite_migrations import run_sqlite_migrations


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
        ensure_models_registered()
        with self.engine.begin() as connection:
            Base.metadata.create_all(connection)
            if _is_sqlite_url(self._url):
                run_sqlite_migrations(connection)

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
