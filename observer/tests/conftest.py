"""Shared test fixtures for observer tests."""

import observer.constants as c
import pytest
from observer.services import config
from observer.services.db import Base, Database
from testcontainers.postgres import PostgresContainer

_PG_IMAGE = "docker.io/pgvector/pgvector:pg17"


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect observer config to a temp directory for every test.

    Prevents tests from reading or overwriting the real
    ~/.basecamp/observer/config.json.
    """
    obs = tmp_path / "observer"
    obs.mkdir()
    monkeypatch.setattr(c, "OBSERVER_DIR", obs)
    monkeypatch.setattr(config, "OBSERVER_DIR", obs)
    monkeypatch.setattr(config, "CONFIG_FILE", obs / "config.json")


@pytest.fixture(scope="session")
def pg_url():
    """Start a pgvector container for the test session and yield its URL."""
    with PostgresContainer(_PG_IMAGE) as pg:
        yield pg.get_connection_url()


@pytest.fixture
def db(pg_url, monkeypatch) -> Database:
    """Create an isolated per-test database against the session container.

    Creates a fresh schema on setup and drops all tables on teardown.
    """
    monkeypatch.setattr(Database, "_instance", None)
    monkeypatch.setattr(Database, "_url", None)
    Database.configure(pg_url)
    database = Database()

    yield database

    # Some tests (e.g. daemon shutdown) call db.close(), which disposes the
    # engine. Reconnect for cleanup if that happened.
    if not hasattr(database, "_engine"):
        Database.configure(pg_url)
        database = Database()

    Base.metadata.drop_all(database._engine)
    database.close()
