"""Shared test fixtures for observer tests."""

import basecamp.constants as bc
import pytest
from basecamp.settings import Settings
from observer.llm import agents
from observer.llm.agents import ExtractionResult, SummaryResult
from observer.services.db import Database
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    """Redirect config to a temp directory for every test.

    Patches the basecamp.settings singleton to use a temp config file,
    preventing tests from reading or overwriting real config.
    """
    obs = tmp_path / "observer"
    obs.mkdir()
    monkeypatch.setattr(bc, "OBSERVER_DIR", obs)
    monkeypatch.setattr(bc, "OBSERVER_LOG_FILE", obs / "observer.log")

    # Redirect the settings singleton to a temp config.json
    test_settings = Settings(path=tmp_path / "config.json")
    monkeypatch.setattr("basecamp.settings.settings", test_settings)
    monkeypatch.setattr("basecamp.settings.settings", test_settings)

    # Clear session env vars so tests don't inherit the host session's state.
    monkeypatch.delenv("BASECAMP_REPO", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


@pytest.fixture(autouse=True)
def _mock_agents(monkeypatch):
    """Replace LLM agents with TestModel-backed agents for all tests.

    This prevents any test from needing real API keys. The TestModel
    generates structured output that satisfies each agent's output_type.
    Individual tests can further override via Agent.override() or
    unittest.mock.patch as needed.
    """
    test_agents = {
        "tool_summarizer": Agent(
            TestModel(custom_output_args={"summary": "test summary"}),
            output_type=SummaryResult,
        ),
        "thinking_summarizer": Agent(
            TestModel(custom_output_args={"summary": "test thinking summary"}),
            output_type=SummaryResult,
        ),
        "section_extractor": Agent(
            TestModel(
                custom_output_args={
                    "title": "Test Session",
                    "summary": "Test summary",
                    "knowledge": "Test knowledge",
                    "decisions": "Test decisions",
                    "constraints": "Test constraints",
                    "actions": "Test actions",
                }
            ),
            output_type=ExtractionResult,
        ),
    }
    monkeypatch.setattr(agents, "_cache", test_agents)


@pytest.fixture
def db(tmp_path, monkeypatch) -> Database:
    """Create an isolated per-test SQLite database.

    Creates a fresh schema on setup and cleans up on teardown.
    """
    db_path = tmp_path / "test_observer.db"
    db_url = f"sqlite:///{db_path}"

    monkeypatch.setattr(bc, "OBSERVER_DIR", tmp_path)
    monkeypatch.setattr(bc, "OBSERVER_DB_PATH", db_path)
    monkeypatch.setattr(bc, "OBSERVER_DB_URL", db_url)

    # Patch module-level bindings captured at import time
    monkeypatch.setattr("observer.services.db.DB_URL", db_url)
    monkeypatch.setattr("observer.services.db.OBSERVER_DIR", tmp_path)

    monkeypatch.setattr(Database, "_instance", None)
    monkeypatch.setattr(Database, "_url", None)
    Database.configure(db_url)
    database = Database()

    yield database

    database.close()
