from __future__ import annotations

import json
from pathlib import Path

import pytest
from pi_memory.db import Database, MemorySession, Observation, Transcript, TranscriptEntry
from pi_memory.ingest import ObserveInput, TranscriptFileMissingError, TranscriptIngestService
from sqlalchemy import func, select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


@pytest.fixture
def service(database: Database) -> TranscriptIngestService:
    return TranscriptIngestService(database=database)


def write_transcript(path: Path, content: bytes) -> None:
    path.write_bytes(content)


def session_line(entry_id: str = "session-1", *, cwd: str | None = None) -> bytes:
    payload = {"type": "session", "id": entry_id}
    if cwd is not None:
        payload["cwd"] = cwd
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def fork_session_line(entry_id: str, parent_path: Path) -> bytes:
    payload = {"type": "session", "id": entry_id, "parentSession": str(parent_path)}
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode()


def message_line(entry_id: str, parent_id: str | None = None, role: str = "user") -> bytes:
    parent = "" if parent_id is None else f',"parentId":"{parent_id}"'
    return f'{{"type":"message","id":"{entry_id}"{parent},"message":{{"role":"{role}"}}}}\n'.encode()


def transcript_entries(database: Database) -> list[TranscriptEntry]:
    with database.session() as db_session:
        return list(db_session.scalars(select(TranscriptEntry).order_by(TranscriptEntry.byte_start)))


def transcript_for(database: Database, session_id: str, path: Path) -> Transcript | None:
    with database.session() as db_session:
        memory_session = db_session.scalar(select(MemorySession).where(MemorySession.session_id == session_id))
        if memory_session is None:
            return None
        return db_session.scalar(
            select(Transcript).where(Transcript.session_id == memory_session.id, Transcript.path == str(path)),
        )


def test_observe_empty_file_creates_cursor_state_without_entries(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, b"")

    result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert result.session_id == "pi-session-1"
    assert result.entries_ingested == 0
    assert result.cursor_offset == 0
    assert result.file_size == 0
    assert result.malformed_lines == 0
    assert result.unsupported_lines == 0
    assert transcript_entries(database) == []
    assert transcript_for(database, "pi-session-1", path).cursor_offset == 0


def test_observe_first_ingest_persists_parsed_pi_entries(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    first_line = session_line()
    second_line = message_line("message-1", parent_id="session-1", role="assistant")
    write_transcript(path, first_line + second_line)

    result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    entries = transcript_entries(database)
    assert result.entries_ingested == 2
    assert result.cursor_offset == len(first_line) + len(second_line)
    assert result.file_size == len(first_line) + len(second_line)
    assert [entry.entry_id for entry in entries] == ["session-1", "message-1"]
    assert entries[1].parent_id == "session-1"
    assert entries[1].entry_type == "message"
    assert entries[1].message_role == "assistant"
    assert entries[1].raw_line == second_line.decode()
    assert entries[1].byte_start == len(first_line)
    assert entries[1].byte_end == len(first_line) + len(second_line)


def test_observe_repeated_call_is_idempotent(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, session_line() + message_line("message-1"))

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.entries_ingested == 2
    assert second_result.entries_ingested == 0
    assert second_result.cursor_offset == first_result.cursor_offset
    with database.session() as db_session:
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
        observation_count = db_session.scalar(select(func.count()).select_from(Observation))
    assert entry_count == 2
    assert observation_count == 2


def test_observe_ingests_only_appended_entries(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    initial_content = session_line()
    appended_line = message_line("message-1")
    write_transcript(path, initial_content)

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    write_transcript(path, initial_content + appended_line)
    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.entries_ingested == 1
    assert second_result.entries_ingested == 1
    assert second_result.cursor_offset == len(initial_content) + len(appended_line)
    assert [entry.entry_id for entry in transcript_entries(database)] == ["session-1", "message-1"]


def test_observe_clamps_stale_cursor_when_transcript_shrinks(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    initial_content = session_line() + message_line("message-1")
    shrunk_content = session_line()
    write_transcript(path, initial_content)

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    write_transcript(path, shrunk_content)
    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.cursor_offset == len(initial_content)
    assert second_result.entries_ingested == 0
    assert second_result.cursor_offset == len(shrunk_content)
    assert second_result.file_size == len(shrunk_content)
    assert transcript_for(database, "pi-session-1", path).cursor_offset == len(shrunk_content)


def test_observe_does_not_consume_partial_trailing_line_until_completed(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    complete_line = session_line()
    partial_line = b'{"type":"message","id":"message-1","message":{"role":"user"}'
    write_transcript(path, complete_line + partial_line)

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    write_transcript(path, complete_line + partial_line + b"}\n")
    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.entries_ingested == 1
    assert first_result.cursor_offset == len(complete_line)
    assert first_result.file_size == len(complete_line) + len(partial_line)
    assert second_result.entries_ingested == 1
    assert second_result.cursor_offset == second_result.file_size
    assert [entry.entry_id for entry in transcript_entries(database)] == ["session-1", "message-1"]


def test_observe_skips_malformed_and_unsupported_complete_lines_while_ingesting_valid_lines(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    malformed_line = b'{"type":"message",\n'
    unsupported_line = b'{"type":123,"id":"unsupported-1"}\n'
    valid_line = message_line("message-1")
    write_transcript(path, malformed_line + unsupported_line + valid_line)

    result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert result.entries_ingested == 1
    assert result.malformed_lines == 1
    assert result.unsupported_lines == 1
    assert result.cursor_offset == result.file_size
    assert [entry.entry_id for entry in transcript_entries(database)] == ["message-1"]


def test_observe_persists_all_typed_pi_entries(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    custom_message_line = b'{"type":"custom_message","id":"custom-message-1","message":{"role":"assistant"}}\n'
    session_info_line = b'{"type":"session_info","id":"session-info-1"}\n'
    thinking_level_change_line = b'{"type":"thinking_level_change","id":"thinking-level-1"}\n'
    custom_line = b'{"type":"custom","id":"custom-1"}\n'
    compaction_line = b'{"type":"compaction","id":"compaction-1"}\n'
    write_transcript(
        path,
        custom_message_line + session_info_line + thinking_level_change_line + custom_line + compaction_line,
    )

    result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    entries = transcript_entries(database)
    assert result.entries_ingested == 5
    assert [entry.entry_type for entry in entries] == [
        "custom_message",
        "session_info",
        "thinking_level_change",
        "custom",
        "compaction",
    ]
    assert [entry.entry_id for entry in entries] == [
        "custom-message-1",
        "session-info-1",
        "thinking-level-1",
        "custom-1",
        "compaction-1",
    ]
    assert entries[0].message_role == "assistant"


def test_observe_child_after_parent_resolves_transcript_lineage(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    parent_path = tmp_path / "parent.jsonl"
    child_path = tmp_path / "child.jsonl"
    write_transcript(parent_path, session_line("parent-session"))
    write_transcript(child_path, fork_session_line("child-session", parent_path) + message_line("child-message"))

    parent_result = service.observe(ObserveInput(session_id="pi-parent", transcript_path=parent_path))
    child_result = service.observe(ObserveInput(session_id="pi-child", transcript_path=child_path))
    repeated_child_result = service.observe(ObserveInput(session_id="pi-child", transcript_path=child_path))

    child_transcript = transcript_for(database, "pi-child", child_path)
    assert child_result.entries_ingested == 2
    assert repeated_child_result.entries_ingested == 0
    assert child_transcript.parent_transcript_path == str(parent_path)
    assert child_transcript.parent_transcript_id == parent_result.transcript_id


def test_observe_child_before_parent_stores_path_then_parent_links_pending_child(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    parent_path = tmp_path / "parent.jsonl"
    child_path = tmp_path / "child.jsonl"
    write_transcript(child_path, fork_session_line("child-session", parent_path))

    child_result = service.observe(ObserveInput(session_id="pi-child", transcript_path=child_path))
    child_transcript = transcript_for(database, "pi-child", child_path)

    assert child_result.entries_ingested == 1
    assert child_transcript.parent_transcript_path == str(parent_path)
    assert child_transcript.parent_transcript_id is None

    write_transcript(parent_path, session_line("parent-session"))
    parent_result = service.observe(ObserveInput(session_id="pi-parent", transcript_path=parent_path))

    child_transcript = transcript_for(database, "pi-child", child_path)
    assert child_transcript.parent_transcript_path == str(parent_path)
    assert child_transcript.parent_transcript_id == parent_result.transcript_id


def test_observe_duplicate_entry_ids_are_scoped_per_transcript(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    parent_path = tmp_path / "parent.jsonl"
    child_path = tmp_path / "child.jsonl"
    write_transcript(parent_path, session_line("copied-session") + message_line("copied-message"))
    write_transcript(child_path, fork_session_line("copied-session", parent_path) + message_line("copied-message"))

    parent_result = service.observe(ObserveInput(session_id="pi-parent", transcript_path=parent_path))
    child_result = service.observe(ObserveInput(session_id="pi-child", transcript_path=child_path))

    assert parent_result.entries_ingested == 2
    assert child_result.entries_ingested == 2
    with database.session() as db_session:
        entry_counts = dict(
            db_session.execute(
                select(Transcript.path, func.count(TranscriptEntry.id)).join(TranscriptEntry).group_by(Transcript.path),
            ).all(),
        )
        total_entries = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
    assert entry_counts == {str(parent_path): 2, str(child_path): 2}
    assert total_entries == 4


def test_observe_missing_transcript_raises_custom_error_without_db_rows(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    missing_path = tmp_path / "missing.jsonl"

    with pytest.raises(TranscriptFileMissingError, match="Transcript file does not exist"):
        service.observe(ObserveInput(session_id="pi-session-1", transcript_path=missing_path))

    with database.session() as db_session:
        session_count = db_session.scalar(select(func.count()).select_from(MemorySession))
        transcript_count = db_session.scalar(select(func.count()).select_from(Transcript))
        observation_count = db_session.scalar(select(func.count()).select_from(Observation))
    assert session_count == 0
    assert transcript_count == 0
    assert observation_count == 0


def test_observe_cursor_state_survives_database_reopen(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    url = sqlite_url(db_path)
    path = tmp_path / "transcript.jsonl"
    initial_content = session_line()
    appended_line = message_line("message-1")
    write_transcript(path, initial_content)

    first_database = Database(url)
    first_database.initialize()
    try:
        first_service = TranscriptIngestService(database=first_database)
        first_result = first_service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    finally:
        first_database.close_if_open()

    write_transcript(path, initial_content + appended_line)
    second_database = Database(url)
    second_database.initialize()
    try:
        second_service = TranscriptIngestService(database=second_database)
        second_result = second_service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
        entries = transcript_entries(second_database)
    finally:
        second_database.close_if_open()

    assert first_result.cursor_offset == len(initial_content)
    assert second_result.entries_ingested == 1
    assert second_result.cursor_offset == len(initial_content) + len(appended_line)
    assert [entry.entry_id for entry in entries] == ["session-1", "message-1"]


def test_observe_multi_session_and_transcript_cursors_are_independent(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    shared_path = tmp_path / "shared.jsonl"
    other_path = tmp_path / "other.jsonl"
    shared_initial = session_line("shared-session")
    shared_append = message_line("shared-message")
    other_content = session_line("other-session")
    write_transcript(shared_path, shared_initial)
    write_transcript(other_path, other_content)

    session_one_first = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=shared_path))
    session_two_result = service.observe(ObserveInput(session_id="pi-session-2", transcript_path=shared_path))
    session_one_other = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=other_path))
    write_transcript(shared_path, shared_initial + shared_append)
    session_one_second = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=shared_path))

    assert session_one_first.entries_ingested == 1
    assert session_two_result.entries_ingested == 1
    assert session_one_other.entries_ingested == 1
    assert session_one_second.entries_ingested == 1
    with database.session() as db_session:
        transcripts = list(db_session.scalars(select(Transcript).order_by(Transcript.session_id, Transcript.path)))
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
    assert len(transcripts) == 3
    assert entry_count == 4
    assert transcript_for(database, "pi-session-1", shared_path).cursor_offset == len(shared_initial) + len(
        shared_append,
    )
    assert transcript_for(database, "pi-session-2", shared_path).cursor_offset == len(shared_initial)
    assert transcript_for(database, "pi-session-1", other_path).cursor_offset == len(other_content)


def test_observe_populates_session_cwd_from_transcript_session_event(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, session_line(cwd="/launch/basecamp"))

    service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    with database.session() as db_session:
        memory_session = db_session.scalar(select(MemorySession).where(MemorySession.session_id == "pi-session-1"))

    assert memory_session.cwd == "/launch/basecamp"
    assert not hasattr(memory_session, "repo_name")
    assert not hasattr(memory_session, "repo_root")


def test_observe_explicit_cwd_wins_over_transcript_cwd_and_worktree_metadata_is_optional(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, session_line(cwd="/launch/basecamp"))

    service.observe(
        ObserveInput(
            session_id="pi-session-1",
            transcript_path=path,
            cwd="/explicit/cwd",
            worktree_label="first",
        ),
    )
    service.observe(
        ObserveInput(
            session_id="pi-session-1",
            transcript_path=path,
            cwd="/explicit/cwd-2",
            worktree_path="/worktrees/second",
        ),
    )

    with database.session() as db_session:
        memory_session = db_session.scalar(select(MemorySession).where(MemorySession.session_id == "pi-session-1"))

    assert memory_session.cwd == "/explicit/cwd-2"
    assert memory_session.worktree_label == "first"
    assert memory_session.worktree_path == "/worktrees/second"


def test_observe_records_observation_with_request_metadata(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    write_transcript(path, session_line())

    result = service.observe(
        ObserveInput(
            session_id="pi-session-1",
            transcript_path=path,
            request_id="request-1",
            request_metadata={"trigger": "test"},
        ),
    )

    with database.session() as db_session:
        observation = db_session.scalar(select(Observation))

    assert observation.id == result.observation_id
    assert observation.session_id is not None
    assert observation.transcript_id == result.transcript_id
    assert observation.request_id == "request-1"
    assert observation.request_metadata == {"trigger": "test"}
    assert result.observed_at is not None


def test_observe_skips_duplicate_entries_from_cursor_replay(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    content = session_line() + message_line("message-1")
    write_transcript(path, content)

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    with database.session() as db_session:
        transcript = db_session.scalar(select(Transcript))
        transcript.cursor_offset = 0

    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.entries_ingested == 2
    assert second_result.entries_ingested == 0
    assert second_result.cursor_offset == len(content)
    with database.session() as db_session:
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
    assert entry_count == 2


def test_observe_skips_idless_duplicate_entries_by_byte_span(
    tmp_path,
    database: Database,
    service: TranscriptIngestService,
) -> None:
    path = tmp_path / "transcript.jsonl"
    content = b'{"type":"model_change","model":"test-model"}\n'
    write_transcript(path, content)

    first_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))
    with database.session() as db_session:
        transcript = db_session.scalar(select(Transcript))
        transcript.cursor_offset = 0

    second_result = service.observe(ObserveInput(session_id="pi-session-1", transcript_path=path))

    assert first_result.entries_ingested == 1
    assert second_result.entries_ingested == 0
    with database.session() as db_session:
        entry_count = db_session.scalar(select(func.count()).select_from(TranscriptEntry))
    assert entry_count == 1
