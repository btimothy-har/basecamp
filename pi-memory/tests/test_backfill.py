from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from pi_memory.cli.backfill import MISSING_SESSION_ID_REASON, run_raw_backfill
from pi_memory.db.database import Database
from pi_memory.db.models import Job, MemorySession, Observation, Transcript, TranscriptEntry
from pi_memory.main import main
from sqlalchemy import func, select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def write_transcript(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def session_line(session_id: str = "pi-session-1") -> bytes:
    return f'{{"type":"session","id":"{session_id}","cwd":"/workspace"}}\n'.encode()


def message_line(entry_id: str = "message-1", parent_id: str = "pi-session-1") -> bytes:
    return f'{{"type":"message","id":"{entry_id}","parentId":"{parent_id}","message":{{"role":"user"}}}}\n'.encode()


def database_counts(db_url: str) -> dict[str, int]:
    database = Database(db_url)
    try:
        database.initialize()
        with database.session() as session:
            return {
                "sessions": session.scalar(select(func.count()).select_from(MemorySession)),
                "transcripts": session.scalar(select(func.count()).select_from(Transcript)),
                "entries": session.scalar(select(func.count()).select_from(TranscriptEntry)),
                "observations": session.scalar(select(func.count()).select_from(Observation)),
                "jobs": session.scalar(select(func.count()).select_from(Job)),
            }
    finally:
        database.close_if_open()


def transcript_entry_ids(db_url: str) -> list[str | None]:
    database = Database(db_url)
    try:
        database.initialize()
        with database.session() as session:
            return list(session.scalars(select(TranscriptEntry.entry_id).order_by(TranscriptEntry.byte_start)))
    finally:
        database.close_if_open()


def test_run_raw_backfill_imports_valid_transcripts_without_jobs(tmp_path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    root = tmp_path / "sessions"
    transcript_path = root / "session.jsonl"
    write_transcript(transcript_path, session_line() + message_line())

    result = run_raw_backfill(db_url=db_url, roots=[root])

    assert result.discovered == 1
    assert result.imported == 1
    assert result.skipped == 0
    assert result.errors == 0
    assert result.entries_ingested == 2
    file = result.files[0]
    assert file.path == transcript_path
    assert file.status == "imported"
    assert file.session_id == "pi-session-1"
    assert file.ingest_result is not None
    assert file.ingest_result.entries_ingested == 2
    assert database_counts(db_url) == {
        "sessions": 1,
        "transcripts": 1,
        "entries": 2,
        "observations": 1,
        "jobs": 0,
    }
    assert transcript_entry_ids(db_url) == ["pi-session-1", "message-1"]


def test_run_raw_backfill_skips_transcripts_missing_embedded_session_id(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    root = tmp_path / "sessions"
    transcript_path = root / "missing-session.jsonl"
    write_transcript(transcript_path, message_line())

    result = run_raw_backfill(db_url=sqlite_url(db_path), roots=[root])

    assert result.discovered == 1
    assert result.imported == 0
    assert result.skipped == 1
    assert result.entries_ingested == 0
    assert result.files[0].path == transcript_path
    assert result.files[0].status == "skipped"
    assert result.files[0].session_id is None
    assert result.files[0].reason == MISSING_SESSION_ID_REASON
    assert not db_path.exists()


def test_run_raw_backfill_dry_run_does_not_create_database(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    root = tmp_path / "sessions"
    transcript_path = root / "session.jsonl"
    write_transcript(transcript_path, session_line())

    result = run_raw_backfill(db_url=sqlite_url(db_path), roots=[root], dry_run=True)

    assert result.dry_run is True
    assert result.discovered == 1
    assert result.would_import == 1
    assert result.imported == 0
    assert result.entries_ingested == 0
    assert result.files[0].path == transcript_path
    assert result.files[0].status == "would_import"
    assert result.files[0].session_id == "pi-session-1"
    assert not db_path.exists()


def test_backfill_cli_reports_json_counts_and_file_results(tmp_path) -> None:
    db_url = sqlite_url(tmp_path / "memory.db")
    root = tmp_path / "sessions"
    valid_path = root / "valid.jsonl"
    invalid_path = root / "invalid.jsonl"
    write_transcript(valid_path, session_line() + message_line())
    write_transcript(invalid_path, message_line("orphan-message"))

    result = CliRunner().invoke(
        main,
        ["backfill", "--root", str(root), "--db-url", db_url, "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["db_url"] == db_url
    assert payload["dry_run"] is False
    assert payload["roots"] == [str(root)]
    assert payload["counts"] == {
        "discovered": 2,
        "imported": 1,
        "would_import": 0,
        "skipped": 1,
        "errors": 0,
        "entries_ingested": 2,
    }
    assert [file["path"] for file in payload["files"]] == [str(invalid_path), str(valid_path)]
    assert payload["files"][0]["status"] == "skipped"
    assert payload["files"][0]["reason"] == MISSING_SESSION_ID_REASON
    assert payload["files"][1]["status"] == "imported"
    assert payload["files"][1]["session_id"] == "pi-session-1"
    assert payload["files"][1]["entries_ingested"] == 2
    assert database_counts(db_url)["jobs"] == 0


def test_backfill_cli_dry_run_reports_human_summary_without_writing(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    root = tmp_path / "sessions"
    write_transcript(root / "session.jsonl", session_line())

    result = CliRunner().invoke(
        main,
        ["backfill", "--root", str(root), "--db-url", sqlite_url(db_path), "--dry-run"],
    )

    assert result.exit_code == 0
    assert "Backfill dry run" in result.output
    assert "would_import: 1" in result.output
    assert "imported: 0" in result.output
    assert not db_path.exists()
