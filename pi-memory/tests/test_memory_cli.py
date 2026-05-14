import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pi_memory.cli.main as cli_module
import pytest
from click.testing import CliRunner
from pi_memory.db import Database, MemorySession, Observation, TranscriptEntry
from pi_memory.ingest import TranscriptIngestService
from pi_memory.server import ServerState
from sqlalchemy import func, select


@contextmanager
def occupied_tcp_port(host: str) -> Iterator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        listener.listen()
        yield listener.getsockname()[1]


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def memory_database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def cli_ingest_service(memory_database: Database) -> TranscriptIngestService:
    return TranscriptIngestService(database=memory_database)


@pytest.fixture
def use_cli_ingest_service(monkeypatch, cli_ingest_service: TranscriptIngestService) -> TranscriptIngestService:
    monkeypatch.setattr(cli_module, "TranscriptIngestService", lambda: cli_ingest_service)
    return cli_ingest_service


def write_transcript(path: Path, content: bytes | None = None) -> None:
    path.write_bytes(content or b'{"type":"session","id":"session-1"}\n')


@pytest.mark.usefixtures("use_cli_ingest_service")
def test_observe_reports_human_readable_ingest_diagnostics(tmp_path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "observe",
            "--session-id",
            "pi-session-1",
            "--transcript-path",
            str(transcript_path),
        ],
    )

    assert result.exit_code == 0
    assert "Observed transcript" in result.output
    assert "  session_id: pi-session-1" in result.output
    assert "  transcript_id: 1" in result.output
    assert "  entries_ingested: 1" in result.output
    assert f"  cursor_offset: {transcript_path.stat().st_size}" in result.output
    assert f"  file_size: {transcript_path.stat().st_size}" in result.output
    assert "  observed_at: " in result.output
    assert "  malformed_lines: 0" in result.output
    assert "  unsupported_lines: 0" in result.output


@pytest.mark.usefixtures("use_cli_ingest_service")
def test_observe_reports_json_ingest_diagnostics(tmp_path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "observe",
            "--session-id",
            "pi-session-1",
            "--transcript-path",
            str(transcript_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "session_id": "pi-session-1",
        "transcript_id": 1,
        "entries_ingested": 1,
        "cursor_offset": transcript_path.stat().st_size,
        "file_size": transcript_path.stat().st_size,
        "observed_at": payload["observed_at"],
        "malformed_lines": 0,
        "unsupported_lines": 0,
    }
    assert isinstance(payload["observed_at"], str)
    assert payload["observed_at"]


@pytest.mark.usefixtures("use_cli_ingest_service")
def test_observe_repeated_cli_call_is_idempotent(tmp_path, memory_database: Database) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path)
    runner = CliRunner()
    args = [
        "observe",
        "--session-id",
        "pi-session-1",
        "--transcript-path",
        str(transcript_path),
        "--json",
    ]

    first_result = runner.invoke(cli_module.main, args)
    second_result = runner.invoke(cli_module.main, args)

    assert first_result.exit_code == 0
    assert second_result.exit_code == 0
    assert json.loads(first_result.output)["entries_ingested"] == 1
    assert json.loads(second_result.output)["entries_ingested"] == 0
    with memory_database.session() as db_session:
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
        observation_count = db_session.scalar(select(func.count()).select_from(Observation))
    assert entry_count == 1
    assert observation_count == 2


@pytest.mark.usefixtures("use_cli_ingest_service")
def test_observe_stores_cli_metadata(tmp_path, memory_database: Database) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "observe",
            "--session-id",
            "pi-session-1",
            "--transcript-path",
            str(transcript_path),
            "--cwd",
            "/workspace/basecamp",
            "--repo-name",
            "basecamp",
            "--repo-root",
            "/workspace/basecamp",
            "--worktree-label",
            "task-1",
            "--worktree-path",
            "/worktrees/basecamp/task-1",
            "--request-id",
            "request-1",
        ],
    )

    assert result.exit_code == 0
    with memory_database.session() as db_session:
        memory_session = db_session.scalar(select(MemorySession).where(MemorySession.session_id == "pi-session-1"))
        observation = db_session.scalar(select(Observation))
    assert memory_session.cwd == "/workspace/basecamp"
    assert memory_session.repo_name == "basecamp"
    assert memory_session.repo_root == "/workspace/basecamp"
    assert memory_session.worktree_label == "task-1"
    assert memory_session.worktree_path == "/worktrees/basecamp/task-1"
    assert observation.request_id == "request-1"


@pytest.mark.usefixtures("use_cli_ingest_service")
def test_observe_missing_transcript_reports_click_error(tmp_path) -> None:
    missing_path = tmp_path / "missing.jsonl"
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "observe",
            "--session-id",
            "pi-session-1",
            "--transcript-path",
            str(missing_path),
        ],
    )

    assert result.exit_code == 1
    assert f"Error: Transcript file does not exist: {missing_path}" in result.output


def test_observe_requires_non_empty_session_id(tmp_path) -> None:
    transcript_path = tmp_path / "transcript.jsonl"
    write_transcript(transcript_path)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "observe",
            "--session-id",
            "  ",
            "--transcript-path",
            str(transcript_path),
        ],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--session-id': must not be empty" in result.output


def test_serve_reports_occupied_port_and_cleans_state(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(cli_module, "ServerState", lambda: ServerState(memory_dir=tmp_path))
    runner = CliRunner()

    with occupied_tcp_port("127.0.0.1") as port:
        result = runner.invoke(
            cli_module.main,
            ["serve", "--host", "127.0.0.1", "--port", str(port)],
        )

    state = ServerState(memory_dir=tmp_path)
    assert result.exit_code == 1
    assert "Error: pi-memory cannot start at http://127.0.0.1:" in result.output
    assert "the port is already in use by another process" in result.output
    assert not state.lock_path.exists()
    assert not state.metadata_path.exists()
