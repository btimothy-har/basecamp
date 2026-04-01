"""Shared test fixtures for observer tests."""

import observer.constants as c
import pytest
from observer.services import config
from observer.services.db import Database


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

    # Clear session env vars so tests don't inherit the host session's state.
    monkeypatch.delenv("BASECAMP_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


@pytest.fixture
def db(tmp_path, monkeypatch) -> Database:
    """Create an isolated per-test SQLite database.

    Creates a fresh schema on setup and cleans up on teardown.
    """
    db_path = tmp_path / "test_observer.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(c, "BASECAMP_DIR", tmp_path)
    monkeypatch.setattr("observer.services.db.BASECAMP_DIR", tmp_path)
    monkeypatch.setattr(c, "DB_PATH", db_path)
    monkeypatch.setattr(c, "DB_URL", db_url)

    monkeypatch.setattr(Database, "_instance", None)
    monkeypatch.setattr(Database, "_url", None)
    Database.configure(db_url)
    database = Database()

    yield database

    database.close()
