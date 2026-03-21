"""SQLAlchemy engine, session factory, and declarative base for observer."""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager

from pgvector.psycopg2 import register_vector
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from observer.exceptions import DatabaseClosedError, DatabaseNotConfiguredError
from observer.services.config import get_pg_url

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all observer tables."""


def _on_connect(dbapi_conn: object, _connection_record: object) -> None:
    """Register the pgvector type adapter on every new connection."""
    register_vector(dbapi_conn)  # type: ignore[arg-type]


class Database:
    """SQLAlchemy engine and session factory for observer.

    Call :meth:`configure` once before first use to set the connection URL.
    ``Database()`` always returns the singleton instance, creating it on
    first access using the configured URL. Resolution order: :meth:`configure`
    → ``OBSERVER_PG_URL`` env var → config file (``~/.basecamp/observer/config.json``).
    """

    _instance: Database | None = None
    _url: str | None = None

    @classmethod
    def configure(cls, url: str) -> None:
        """Set the connection URL and reset the singleton."""
        if cls._instance is not None:
            cls._instance.close()
        cls._url = url

    @classmethod
    def close_if_open(cls) -> None:
        """Close and dispose the singleton if one exists."""
        if cls._instance is not None:
            cls._instance.close()

    def __new__(cls) -> Database:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if hasattr(self, "_engine"):
            return

        url = type(self)._url or os.environ.get("OBSERVER_PG_URL") or get_pg_url()
        if not url:
            raise DatabaseNotConfiguredError()

        # Create the extension before registering the pgvector adapter.
        # register_vector() probes for the vector OID, so it fails if the
        # extension doesn't exist yet. Use a bare engine for the DDL, then
        # rebuild with the adapter attached.
        bootstrap = create_engine(url)
        with bootstrap.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        bootstrap.dispose()

        self._engine: Engine = create_engine(url)
        event.listen(self._engine, "connect", _on_connect)
        self._session_factory: sessionmaker[Session] = sessionmaker(bind=self._engine)

        import observer.data.schemas  # noqa: F401, PLC0415 -- register schemas with Base

        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables and check migration state.

        New installs: ``create_all()`` builds the latest schema and stamps
        the version so no migrations are pending.

        Existing installs: ``create_all()`` handles additive changes. If
        destructive migrations are pending, log a warning — the user must
        run ``observer db migrate`` explicitly.
        """
        from observer.services.migrations import (  # noqa: PLC0415
            needs_migration,
            stamp,
        )

        is_new = not self._has_tables()
        Base.metadata.create_all(self._engine)

        if is_new:
            stamp(self._engine)
        elif needs_migration(self._engine):
            logger.warning("Database schema is outdated. Run 'observer db migrate' to update.")

    def _has_tables(self) -> bool:
        """Check if core tables exist (i.e. not a fresh database)."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM information_schema.tables WHERE table_name = 'transcripts'")
            ).fetchone()
            return row is not None

    @contextmanager
    def session(self) -> Generator[Session]:
        """Yield a session that auto-commits on success, rolls back on error."""
        if not hasattr(self, "_session_factory"):
            raise DatabaseClosedError()
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def close(self) -> None:
        """Dispose the engine, release connections, and clear the singleton."""
        if hasattr(self, "_engine"):
            self._engine.dispose()
            del self._engine
        if hasattr(self, "_session_factory"):
            del self._session_factory
        if type(self)._instance is self:
            type(self)._instance = None
