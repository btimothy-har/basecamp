import json
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pi_memory.cli.main as cli_module
import pytest
from click.testing import CliRunner
from pi_memory.db import (
    ANALYSIS_STATUS_COMPLETED,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    Database,
    Job,
    MemorySession,
    Observation,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
)
from pi_memory.ingest import TranscriptIngestService
from pi_memory.jobs import JobStore
from pi_memory.recall import index_transcript
from pi_memory.server import ServerState
from pi_memory.settings import INTERPRETATION_MODEL_ENV, INTERPRETER_MODE_ENV, Settings
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
def cli_job_store(memory_database: Database) -> JobStore:
    return JobStore(database=memory_database)


@pytest.fixture
def use_cli_ingest_service(monkeypatch, cli_ingest_service: TranscriptIngestService) -> TranscriptIngestService:
    monkeypatch.setattr(cli_module, "TranscriptIngestService", lambda: cli_ingest_service)
    return cli_ingest_service


@pytest.fixture
def use_cli_job_store(monkeypatch, cli_job_store: JobStore) -> JobStore:
    monkeypatch.setattr(cli_module, "JobStore", lambda: cli_job_store)
    return cli_job_store


def write_transcript(path: Path, content: bytes | None = None) -> None:
    path.write_bytes(content or b'{"type":"session","id":"session-1"}\n')


def parse_observe_output(output: str) -> dict[str, str]:
    fields = {}
    for line in output.splitlines():
        if not line.startswith("  "):
            continue
        name, value = line.strip().split(": ", maxsplit=1)
        fields[name] = value
    return fields


def test_config_reports_effective_defaults(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "config.json"
    monkeypatch.delenv(INTERPRETER_MODE_ENV, raising=False)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    monkeypatch.setattr(cli_module, "MemorySettings", lambda: Settings(settings_path))

    result = CliRunner().invoke(cli_module.main, ["config", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "config_path": str(settings_path),
        "interpreter_mode": "deterministic",
        "interpretation_model": None,
    }
    assert not settings_path.exists()


def test_config_persists_interpreter_settings(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "config.json"
    monkeypatch.delenv(INTERPRETER_MODE_ENV, raising=False)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    monkeypatch.setattr(cli_module, "MemorySettings", lambda: Settings(settings_path))

    result = CliRunner().invoke(
        cli_module.main,
        [
            "config",
            "--interpreter-mode",
            "pydantic-ai",
            "--interpretation-model",
            "anthropic:claude-sonnet-4-6",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "config_path": str(settings_path),
        "interpreter_mode": "pydantic-ai",
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }
    assert json.loads(settings_path.read_text()) == {
        "interpreter_mode": "pydantic-ai",
        "interpretation_model": "anthropic:claude-sonnet-4-6",
    }


def test_config_reports_env_overrides(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "config.json"
    Settings(settings_path).update(
        interpreter_mode="pydantic-ai",
        interpretation_model="anthropic:file-model",
    )
    monkeypatch.setenv(INTERPRETER_MODE_ENV, "deterministic")
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:env-model")
    monkeypatch.setattr(cli_module, "MemorySettings", lambda: Settings(settings_path))

    result = CliRunner().invoke(cli_module.main, ["config"])

    assert result.exit_code == 0
    fields = parse_observe_output(result.output)
    assert "Pi memory config" in result.output
    assert fields["config_path"] == str(settings_path)
    assert fields["interpreter_mode"] == "deterministic"
    assert fields["interpretation_model"] == "openai:env-model"


def test_config_rejects_pydantic_ai_without_model(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "memory" / "config.json"
    monkeypatch.delenv(INTERPRETER_MODE_ENV, raising=False)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    monkeypatch.setattr(cli_module, "MemorySettings", lambda: Settings(settings_path))

    result = CliRunner().invoke(cli_module.main, ["config", "--interpreter-mode", "pydantic-ai"])

    assert result.exit_code == 1
    assert "Error: interpretation_model is required when interpreter_mode is 'pydantic-ai'." in result.output
    assert not settings_path.exists()


@pytest.mark.usefixtures("use_cli_ingest_service", "use_cli_job_store")
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
    fields = parse_observe_output(result.output)
    assert "Observed transcript" in result.output
    assert fields["session_id"] == "pi-session-1"
    assert fields["transcript_id"] == "1"
    assert isinstance(int(fields["observation_id"]), int)
    assert fields["entries_ingested"] == "1"
    assert fields["cursor_offset"] == str(transcript_path.stat().st_size)
    assert fields["file_size"] == str(transcript_path.stat().st_size)
    assert fields["observed_at"]
    assert fields["malformed_lines"] == "0"
    assert fields["unsupported_lines"] == "0"
    assert isinstance(int(fields["job_id"]), int)


@pytest.mark.usefixtures("use_cli_ingest_service", "use_cli_job_store")
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
        "observation_id": payload["observation_id"],
        "entries_ingested": 1,
        "cursor_offset": transcript_path.stat().st_size,
        "file_size": transcript_path.stat().st_size,
        "observed_at": payload["observed_at"],
        "malformed_lines": 0,
        "unsupported_lines": 0,
        "job_id": payload["job_id"],
    }
    assert isinstance(payload["observation_id"], int)
    assert isinstance(payload["job_id"], int)
    assert isinstance(payload["observed_at"], str)
    assert payload["observed_at"]


@pytest.mark.usefixtures("use_cli_ingest_service", "use_cli_job_store")
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
    first_payload = json.loads(first_result.output)
    second_payload = json.loads(second_result.output)
    assert first_payload["entries_ingested"] == 1
    assert isinstance(first_payload["job_id"], int)
    assert second_payload["entries_ingested"] == 0
    assert second_payload["job_id"] is None
    with memory_database.session() as db_session:
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
        observation_count = db_session.scalar(select(func.count()).select_from(Observation))
        job_count = db_session.scalar(select(func.count()).select_from(Job))
        job = db_session.scalar(select(Job))
    assert entry_count == 1
    assert observation_count == 2
    assert job_count == 1
    assert job is not None
    assert job.id == first_payload["job_id"]
    assert job.payload_json["observation_id"] == first_payload["observation_id"]
    assert "raw_line" not in job.payload_json


@pytest.mark.usefixtures("use_cli_ingest_service", "use_cli_job_store")
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


@pytest.mark.usefixtures("use_cli_ingest_service", "use_cli_job_store")
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


def test_serve_constructs_dispatcher_and_passes_it_to_app(tmp_path, monkeypatch) -> None:
    dispatcher = object()
    captured: dict[str, object] = {}

    def fake_job_dispatcher() -> object:
        captured["dispatcher_constructed"] = True
        return dispatcher

    def fake_run(app, host: str, port: int) -> None:
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    def fake_ensure_port_available(*, host: str, port: int) -> None:
        captured["ensured_host"] = host
        captured["ensured_port"] = port

    monkeypatch.setattr(cli_module, "ServerState", lambda: ServerState(memory_dir=tmp_path))
    monkeypatch.setattr(cli_module, "JobDispatcher", fake_job_dispatcher)
    monkeypatch.setattr(cli_module.uvicorn, "run", fake_run)
    monkeypatch.setattr(cli_module, "_ensure_port_available", fake_ensure_port_available)

    result = CliRunner().invoke(
        cli_module.main,
        ["serve", "--host", "127.0.0.1", "--port", "8765"],
    )

    assert result.exit_code == 0
    assert captured["dispatcher_constructed"] is True
    assert captured["app"].state.dispatcher is dispatcher
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert "pi-memory stopped" in result.output


def create_job_transcript(database: Database) -> int:
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-cli")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/cli-transcript.jsonl",
            cursor_offset=10,
            file_size=10,
        )
        db_session.add(transcript)
        db_session.flush()
        db_session.add(
            TranscriptEntry(
                transcript_id=transcript.id,
                entry_id="cli-entry-1",
                entry_type="message",
                message_role="user",
                raw_line='{"content":"hidden"}',
                byte_start=0,
                byte_end=10,
            ),
        )
        db_session.flush()
        return transcript.id


def create_interpretation_snapshot(database: Database) -> dict[str, object]:
    now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-interpret-cli")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/cli-secret-transcript.jsonl",
            cursor_offset=300,
            file_size=300,
        )
        transcript.entries.append(
            TranscriptEntry(
                entry_id="cli-interpret-entry-1",
                entry_type="message",
                message_role="assistant",
                raw_line='{"content":"SECRET_RAW_TRANSCRIPT_TOOL_OUTPUT"}',
                byte_start=20,
                byte_end=120,
            ),
        )
        job = Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"safe": True})
        db_session.add_all([transcript, job])
        db_session.flush()
        snapshot = SessionInterpretationSnapshot(
            session_id=memory_session.id,
            transcript_id=transcript.id,
            analysis_run_id=None,
            job_id=job.id,
            status="completed",
            blocked_reason=None,
            analyzed_through_entry_id=transcript.entries[0].id,
            analyzed_through_byte_offset=120,
            origin_counts_json={
                "local_activity_count": 1,
                "inherited_activity_count": 0,
                "mixed_activity_count": 1,
                "unknown_activity_count": 0,
            },
            claim_source_activity_count=2,
            interpretation_json={"summary": "CLI safe interpretation", "claims": []},
            citations_json=[{"claim_id": "claim-cli", "source_ref_id": "ar1:ep0:act0:entries1"}],
            model_metadata_json={"provider": "deterministic", "model": "cli-test"},
            prompt_version="phase5b-session-interpretation-v1",
            schema_version=1,
            created_at=now,
            updated_at=now + timedelta(minutes=1),
        )
        db_session.add(snapshot)
        db_session.flush()
        return {
            "session_row_id": memory_session.id,
            "snapshot_id": snapshot.id,
            "transcript_id": transcript.id,
            "job_id": job.id,
            "entry_id": transcript.entries[0].id,
            "created_at": snapshot.created_at,
            "updated_at": snapshot.updated_at,
        }


def create_recall_transcript(
    database: Database,
    *,
    session_id: str = "pi-session-recall-cli",
    transcript_path: str = "/tmp/pi/cli-recall.jsonl",
    entry_id: str = "cli-recall-entry-1",
    text: str = "Local recall CLI should find the aurora transcript.",
    byte_start: int = 7,
    byte_end: int = 107,
) -> tuple[int, int]:
    with database.session() as db_session:
        memory_session = MemorySession(session_id=session_id)
        transcript = Transcript(
            session=memory_session,
            path=transcript_path,
            cursor_offset=128,
            file_size=128,
        )
        transcript.entries.append(
            TranscriptEntry(
                entry_id=entry_id,
                entry_type="message",
                message_role="user",
                timestamp=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                raw_line=json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "user",
                            "content": text,
                        },
                    },
                ),
                byte_start=byte_start,
                byte_end=byte_end,
            ),
        )
        db_session.add(transcript)
        db_session.flush()
        transcript_id = transcript.id
        stored_entry_id = transcript.entries[0].id
        index_transcript(db_session, transcript_id)
        return transcript_id, stored_entry_id


def get_cli_job(database: Database, job_id: int) -> Job:
    with database.session() as db_session:
        return db_session.get_one(Job, job_id)


def create_inspection_job(database: Database) -> tuple[int, datetime]:
    now = datetime(2026, 1, 1, 10, tzinfo=UTC)
    with database.session() as db_session:
        job = Job(
            kind=JOB_KIND_PROCESS_TRANSCRIPT,
            status=JOB_STATUS_COMPLETED,
            payload_json={"transcript_id": 1, "session_id": "pi-session-cli"},
            result_json={"ok": True},
            priority=3,
            due_at=now,
            attempts=2,
            max_attempts=5,
            run_id="run-1",
            claimed_at=now + timedelta(minutes=1),
            claimed_by="worker-1",
            started_at=now + timedelta(minutes=2),
            heartbeat_at=now + timedelta(minutes=3),
            lease_expires_at=now + timedelta(minutes=4),
            running_pid=123,
            finished_at=now + timedelta(minutes=5),
            exit_code=0,
            last_error="previous failure",
            created_at=now - timedelta(minutes=1),
            updated_at=now + timedelta(minutes=6),
        )
        db_session.add(job)
        db_session.flush()
        return job.id, now


def parse_cli_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def test_interpretation_reports_json_snapshot(memory_database: Database) -> None:
    expected = create_interpretation_snapshot(memory_database)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "interpretation",
            "--session-id",
            "pi-session-interpret-cli",
            "--db-url",
            memory_database.url,
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload == {
        "session_id": "pi-session-interpret-cli",
        "session_row_id": expected["session_row_id"],
        "snapshot_id": expected["snapshot_id"],
        "transcript_id": expected["transcript_id"],
        "analysis_run_id": None,
        "job_id": expected["job_id"],
        "status": "completed",
        "blocked_reason": None,
        "analyzed_through_entry_id": expected["entry_id"],
        "analyzed_through_byte_offset": 120,
        "origin_counts": {
            "local_activity_count": 1,
            "inherited_activity_count": 0,
            "mixed_activity_count": 1,
            "unknown_activity_count": 0,
        },
        "claim_source_activity_count": 2,
        "interpretation_json": {"summary": "CLI safe interpretation", "claims": []},
        "citations_json": [{"claim_id": "claim-cli", "source_ref_id": "ar1:ep0:act0:entries1"}],
        "model_metadata": {"provider": "deterministic", "model": "cli-test"},
        "prompt_version": "phase5b-session-interpretation-v1",
        "schema_version": 1,
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
    }
    assert parse_cli_time(payload["created_at"]) == expected["created_at"]
    assert parse_cli_time(payload["updated_at"]) == expected["updated_at"]
    assert "raw_line" not in payload
    assert "transcript_path" not in payload
    assert "/tmp/pi/cli-secret-transcript.jsonl" not in str(payload)
    assert "SECRET_RAW_TRANSCRIPT_TOOL_OUTPUT" not in str(payload)


def test_interpretation_reports_human_readable_snapshot(memory_database: Database) -> None:
    expected = create_interpretation_snapshot(memory_database)

    result = CliRunner().invoke(
        cli_module.main,
        [
            "interpretation",
            "--session-id",
            "pi-session-interpret-cli",
            "--db-url",
            memory_database.url,
        ],
    )

    assert result.exit_code == 0
    fields = parse_observe_output(result.output)
    assert "Session interpretation" in result.output
    assert fields["session_id"] == "pi-session-interpret-cli"
    assert fields["session_row_id"] == str(expected["session_row_id"])
    assert fields["snapshot_id"] == str(expected["snapshot_id"])
    assert fields["status"] == "completed"
    assert fields["claim_source_activity_count"] == "2"
    assert "origin_counts" in fields
    assert "interpretation_json" in fields
    assert "citations_json" in fields
    assert "model_metadata" in fields
    assert "/tmp/pi/cli-secret-transcript.jsonl" not in result.output
    assert "SECRET_RAW_TRANSCRIPT_TOOL_OUTPUT" not in result.output


def test_interpretation_missing_reports_click_error(memory_database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "interpretation",
            "--session-id",
            "missing-session",
            "--db-url",
            memory_database.url,
        ],
    )

    assert result.exit_code == 1
    assert "Error: Interpretation snapshot for session missing-session was not found" in result.output


def test_recall_reports_human_readable_results(memory_database: Database) -> None:
    create_recall_transcript(memory_database)

    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "aurora transcript", "--db-url", memory_database.url],
    )

    assert result.exit_code == 0
    assert "Recall results for: aurora transcript" in result.output
    assert "1. session=pi-session-recall-cli" in result.output
    assert "source=/tmp/pi/cli-recall.jsonl:7-107" in result.output
    assert "entry=message/user" in result.output
    assert "excerpt=" in result.output
    assert "aurora" in result.output.lower()
    assert "match=Matched raw transcript text for: aurora, transcript" in result.output


def test_recall_reports_json_results(memory_database: Database) -> None:
    transcript_id, entry_id = create_recall_transcript(memory_database)

    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "aurora", "--db-url", memory_database.url, "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["query"] == "aurora"
    assert payload["terms"] == ["aurora"]
    assert payload["match_query"] == '"aurora"'
    assert payload["result_count"] == 1
    hit = payload["results"][0]
    assert hit["result_type"] == "raw_transcript"
    assert hit["rank"] == 1
    assert hit["session_id"] == "pi-session-recall-cli"
    assert hit["transcript_id"] == transcript_id
    assert hit["transcript_path"] == "/tmp/pi/cli-recall.jsonl"
    assert hit["transcript_entry_id"] == entry_id
    assert hit["pi_entry_id"] == "cli-recall-entry-1"
    assert hit["entry_type"] == "message"
    assert hit["message_role"] == "user"
    assert parse_cli_time(hit["timestamp"]) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert hit["byte_start"] == 7
    assert hit["byte_end"] == 107
    assert "aurora" in hit["excerpt"].lower()
    assert hit["match_reason"] == "Matched raw transcript text for: aurora"


def test_recall_limit_option_restricts_json_results(memory_database: Database) -> None:
    create_recall_transcript(
        memory_database,
        session_id="pi-session-recall-limit-1",
        transcript_path="/tmp/pi/cli-recall-limit-1.jsonl",
        entry_id="cli-recall-limit-1",
        text="Shared aurora recall result one.",
        byte_start=0,
        byte_end=50,
    )
    create_recall_transcript(
        memory_database,
        session_id="pi-session-recall-limit-2",
        transcript_path="/tmp/pi/cli-recall-limit-2.jsonl",
        entry_id="cli-recall-limit-2",
        text="Shared aurora recall result two.",
        byte_start=0,
        byte_end=50,
    )

    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "shared aurora", "--db-url", memory_database.url, "--limit", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result_count"] == 1
    assert len(payload["results"]) == 1


def test_recall_session_id_option_filters_json_results(memory_database: Database) -> None:
    create_recall_transcript(
        memory_database,
        session_id="pi-session-recall-other",
        transcript_path="/tmp/pi/cli-recall-other.jsonl",
        entry_id="cli-recall-other",
        text="Filtered aurora recall other session.",
        byte_start=0,
        byte_end=50,
    )
    _transcript_id, entry_id = create_recall_transcript(
        memory_database,
        session_id="pi-session-recall-target",
        transcript_path="/tmp/pi/cli-recall-target.jsonl",
        entry_id="cli-recall-target",
        text="Filtered aurora recall target session.",
        byte_start=0,
        byte_end=50,
    )

    result = CliRunner().invoke(
        cli_module.main,
        [
            "recall",
            "--query",
            "filtered aurora",
            "--db-url",
            memory_database.url,
            "--session-id",
            "pi-session-recall-target",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["result_count"] == 1
    hit = payload["results"][0]
    assert hit["session_id"] == "pi-session-recall-target"
    assert hit["transcript_entry_id"] == entry_id


@pytest.mark.parametrize("limit", ["0", "51"])
def test_recall_rejects_out_of_range_limit(memory_database: Database, limit: str) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "aurora", "--db-url", memory_database.url, "--limit", limit],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--limit'" in result.output


def test_recall_requires_non_empty_session_id(memory_database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "aurora", "--db-url", memory_database.url, "--session-id", "  "],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--session-id': must not be empty" in result.output


def test_recall_reports_empty_results(memory_database: Database) -> None:
    create_recall_transcript(memory_database)

    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "missing", "--db-url", memory_database.url],
    )

    assert result.exit_code == 0
    assert "No recall results for: missing" in result.output


def test_recall_requires_non_empty_query(memory_database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "  ", "--db-url", memory_database.url],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--query': must not be empty" in result.output


def test_recall_requires_non_empty_db_url() -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["recall", "--query", "aurora", "--db-url", "  "],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--db-url': must not be empty" in result.output


def test_job_reports_json_inspection(memory_database: Database) -> None:
    job_id, now = create_inspection_job(memory_database)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        [
            "job",
            "--job-id",
            str(job_id),
            "--db-url",
            memory_database.url,
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == job_id
    assert payload["kind"] == JOB_KIND_PROCESS_TRANSCRIPT
    assert payload["status"] == JOB_STATUS_COMPLETED
    assert payload["payload_json"] == {"transcript_id": 1, "session_id": "pi-session-cli"}
    assert payload["result_json"] == {"ok": True}
    assert payload["attempts"] == 2
    assert payload["max_attempts"] == 5
    assert payload["last_error"] == "previous failure"
    assert parse_cli_time(payload["due_at"]) == now
    assert "raw_line" not in payload
    assert "content" not in payload


def test_job_reports_human_readable_inspection(memory_database: Database) -> None:
    job_id, _now = create_inspection_job(memory_database)
    runner = CliRunner()

    result = runner.invoke(
        cli_module.main,
        ["job", "--job-id", str(job_id), "--db-url", memory_database.url],
    )

    assert result.exit_code == 0
    fields = parse_observe_output(result.output)
    assert "Job" in result.output
    assert fields["id"] == str(job_id)
    assert fields["kind"] == JOB_KIND_PROCESS_TRANSCRIPT
    assert fields["status"] == JOB_STATUS_COMPLETED
    assert fields["attempts"] == "2"
    assert fields["last_error"] == "previous failure"


def test_job_missing_reports_click_error(memory_database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["job", "--job-id", "999", "--db-url", memory_database.url],
    )

    assert result.exit_code == 1
    assert "Error: Job 999 was not found" in result.output


def test_job_help_lists_required_options() -> None:
    result = CliRunner().invoke(cli_module.main, ["job", "--help"])

    assert result.exit_code == 0
    assert "--job-id" in result.output
    assert "--db-url" in result.output
    assert "--json" in result.output


def test_job_requires_non_empty_db_url() -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["job", "--job-id", "1", "--db-url", "  "],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--db-url': must not be empty" in result.output


def test_run_job_succeeds_against_isolated_db(tmp_path) -> None:
    db_url = sqlite_url(tmp_path / "memory-run-job.db")
    database = Database(db_url)
    try:
        database.initialize()
        transcript_id = create_job_transcript(database)
        store = JobStore(database=database)
        store.enqueue(JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"transcript_id": transcript_id})
        claimed = store.claim_next("worker-1")
        assert claimed is not None
        runner = CliRunner()

        result = runner.invoke(
            cli_module.main,
            ["run-job", "--job-id", str(claimed.id), "--run-id", claimed.run_id, "--db-url", db_url],
        )

        assert result.exit_code == 0
        assert f"Job {claimed.id} completed" in result.output
        job = get_cli_job(database, claimed.id)
        assert job.status == JOB_STATUS_COMPLETED
        assert job.attempts == 1
        assert job.result_json is not None
        phase_5a = job.result_json["phase_5a"]
        assert isinstance(phase_5a, dict)
        base_result = {key: value for key, value in job.result_json.items() if key != "phase_5a"}
        assert base_result == {
            "transcript_id": transcript_id,
            "session_id": "pi-session-cli",
            "entry_count": 1,
            "cursor_offset": 10,
            "file_size": 10,
            "indexed_entry_count": 0,
            "interpret_session_job_id": base_result["interpret_session_job_id"],
        }
        assert isinstance(base_result["interpret_session_job_id"], int)
        assert isinstance(phase_5a["analysis_run_id"], int)
        assert phase_5a["status"] == ANALYSIS_STATUS_COMPLETED
        assert phase_5a["activity_count"] == 1
        assert phase_5a["episode_count"] == 1
        assert phase_5a["manifest_count"] == 1
        assert isinstance(phase_5a["snapshot_shell_id"], int)
        assert phase_5a["analyzed_through_byte_offset"] == 10
    finally:
        database.close_if_open()


def test_run_job_wrong_run_id_exits_one_without_incrementing_attempts(tmp_path) -> None:
    db_url = sqlite_url(tmp_path / "memory-run-job-wrong-token.db")
    database = Database(db_url)
    try:
        database.initialize()
        transcript_id = create_job_transcript(database)
        store = JobStore(database=database)
        store.enqueue(JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"transcript_id": transcript_id})
        claimed = store.claim_next("worker-1")
        assert claimed is not None
        runner = CliRunner()

        result = runner.invoke(
            cli_module.main,
            ["run-job", "--job-id", str(claimed.id), "--run-id", "wrong-run", "--db-url", db_url],
        )

        assert result.exit_code == 1
        assert f"Error: Job {claimed.id} run token does not match" in result.output
        job = get_cli_job(database, claimed.id)
        assert job.status == JOB_STATUS_CLAIMED
        assert job.attempts == 0
    finally:
        database.close_if_open()


def test_run_job_help_lists_required_options() -> None:
    result = CliRunner().invoke(cli_module.main, ["run-job", "--help"])

    assert result.exit_code == 0
    assert "--job-id" in result.output
    assert "--run-id" in result.output
    assert "--db-url" in result.output


def test_run_job_requires_non_empty_options(tmp_path) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["run-job", "--job-id", "1", "--run-id", "  ", "--db-url", sqlite_url(tmp_path / "memory.db")],
    )

    assert result.exit_code == 2
    assert "Invalid value for '--run-id': must not be empty" in result.output
