from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import Database, MemorySession, Transcript, TranscriptEntry
from pi_memory.recall import RecallSearchService, index_transcript


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


def message_entry(
    text: str,
    *,
    pi_entry_id: str,
    byte_start: int,
    byte_end: int,
    message_role: str = "user",
    timestamp: datetime | None = None,
) -> TranscriptEntry:
    return TranscriptEntry(
        entry_id=pi_entry_id,
        entry_type="message",
        message_role=message_role,
        timestamp=timestamp,
        raw_line=json.dumps(
            {
                "type": "message",
                "message": {"role": message_role, "content": [{"type": "text", "text": text}]},
            },
        ),
        byte_start=byte_start,
        byte_end=byte_end,
    )


def add_indexed_transcript(
    database: Database,
    *,
    session_id: str,
    path: str,
    entries: list[TranscriptEntry],
) -> tuple[int, list[int]]:
    with database.session() as session:
        memory_session = MemorySession(session_id=session_id, cwd="/tmp/project")
        transcript = Transcript(session=memory_session, path=path, file_size=4096)
        transcript.entries.extend(entries)
        session.add(transcript)
        session.flush()

        transcript_id = transcript.id
        entry_ids = [entry.id for entry in transcript.entries]
        index_transcript(session, transcript_id)

    return transcript_id, entry_ids


def test_search_returns_relevant_raw_transcript_hit_with_canonical_metadata(database: Database) -> None:
    timestamp = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    transcript_id, entry_ids = add_indexed_transcript(
        database,
        session_id="pi-session-1",
        path="/tmp/pi/session-1.jsonl",
        entries=[
            message_entry(
                "The nebula recall implementation should find this transcript line.",
                pi_entry_id="pi-entry-1",
                byte_start=12,
                byte_end=180,
                timestamp=timestamp,
            ),
            message_entry(
                "Unrelated garden notes about orchids.",
                pi_entry_id="pi-entry-2",
                byte_start=181,
                byte_end=260,
            ),
        ],
    )

    result = RecallSearchService(database=database).search("nebula recall")

    assert result.query == "nebula recall"
    assert result.terms == ("nebula", "recall")
    assert result.match_query == '"nebula" "recall"'
    assert len(result.results) == 1

    hit = result.results[0]
    assert hit.result_type == "raw_transcript"
    assert hit.rank == 1
    assert hit.score <= 0
    assert hit.session_id == "pi-session-1"
    assert hit.transcript_id == transcript_id
    assert hit.transcript_path == "/tmp/pi/session-1.jsonl"
    assert hit.transcript_entry_id == entry_ids[0]
    assert hit.pi_entry_id == "pi-entry-1"
    assert hit.entry_type == "message"
    assert hit.message_role == "user"
    assert hit.timestamp is not None
    assert hit.timestamp.year == 2026
    assert hit.byte_start == 12
    assert hit.byte_end == 180
    assert "nebula" in hit.excerpt.lower()
    assert "<mark>" in hit.excerpt
    assert hit.match_reason == "Matched raw transcript text for: nebula, recall"


def test_search_applies_session_filter_before_limit(database: Database) -> None:
    add_indexed_transcript(
        database,
        session_id="pi-session-1",
        path="/tmp/pi/session-1.jsonl",
        entries=[message_entry("shared nebula first", pi_entry_id="first", byte_start=0, byte_end=50)],
    )
    _, second_entry_ids = add_indexed_transcript(
        database,
        session_id="pi-session-2",
        path="/tmp/pi/session-2.jsonl",
        entries=[message_entry("shared nebula second", pi_entry_id="second", byte_start=0, byte_end=51)],
    )

    result = RecallSearchService(database=database).search("nebula", limit=1, session_id="pi-session-2")

    assert len(result.results) == 1
    assert result.results[0].session_id == "pi-session-2"
    assert result.results[0].transcript_entry_id == second_entry_ids[0]


def test_search_clamps_limit_to_supported_bounds(database: Database) -> None:
    add_indexed_transcript(
        database,
        session_id="pi-session-limit",
        path="/tmp/pi/limit.jsonl",
        entries=[
            message_entry(
                f"limit nebula entry {index}",
                pi_entry_id=f"entry-{index}",
                byte_start=index * 10,
                byte_end=(index * 10) + 9,
            )
            for index in range(55)
        ],
    )
    service = RecallSearchService(database=database)

    low_result = service.search("nebula", limit=0)
    high_result = service.search("nebula", limit=99)

    assert len(low_result.results) == 1
    assert len(high_result.results) == 50
    assert high_result.results[0].rank == 1
    assert high_result.results[-1].rank == 50


def test_search_persists_after_database_reopen(tmp_path) -> None:
    db_path = tmp_path / "memory.db"
    first_database = Database(sqlite_url(db_path))
    try:
        first_database.initialize()
        _, entry_ids = add_indexed_transcript(
            first_database,
            session_id="pi-session-reopen",
            path="/tmp/pi/reopen.jsonl",
            entries=[message_entry("persistent nebula memory", pi_entry_id="persisted", byte_start=0, byte_end=80)],
        )
    finally:
        first_database.close_if_open()

    reopened_database = Database(sqlite_url(db_path))
    try:
        result = RecallSearchService(database=reopened_database).search("persistent nebula")
    finally:
        reopened_database.close_if_open()

    assert len(result.results) == 1
    assert result.results[0].session_id == "pi-session-reopen"
    assert result.results[0].transcript_entry_id == entry_ids[0]


@pytest.mark.parametrize(
    ("query", "expected_hits"),
    [
        ("nebula) OR *", 1),
        ('"nebula', 1),
        ("((nebula))", 1),
        ("nebula NEAR/1 recall", 0),
        ("nebula*", 1),
    ],
)
def test_search_handles_awkward_query_strings_without_fts_syntax_errors(
    database: Database,
    query: str,
    expected_hits: int,
) -> None:
    add_indexed_transcript(
        database,
        session_id="pi-session-awkward",
        path="/tmp/pi/awkward.jsonl",
        entries=[message_entry("awkward nebula recall", pi_entry_id="awkward", byte_start=0, byte_end=70)],
    )

    result = RecallSearchService(database=database).search(query)

    assert len(result.results) == expected_hits
    for hit in result.results:
        assert hit.result_type == "raw_transcript"


@pytest.mark.parametrize("query", ["", "   ", "OR * ()", "!!!"])
def test_search_returns_no_results_for_empty_or_no_token_query(database: Database, query: str) -> None:
    add_indexed_transcript(
        database,
        session_id="pi-session-empty",
        path="/tmp/pi/empty.jsonl",
        entries=[message_entry("empty nebula should not matter", pi_entry_id="empty", byte_start=0, byte_end=60)],
    )

    result = RecallSearchService(database=database).search(query)

    assert result.terms == ()
    assert result.match_query is None
    assert result.results == ()
