from pathlib import Path

from pi_memory.db import Base, Database
from sqlalchemy import text


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


def test_base_is_available_for_schema_registration() -> None:
    assert Base.metadata is not None
