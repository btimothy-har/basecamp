from __future__ import annotations

import json
from pathlib import Path

import pytest
from pi_memory.db import Database, MemorySession, Transcript, TranscriptEntry
from pi_memory.recall import extract_search_text, index_transcript
from sqlalchemy import text


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


def entry(raw_payload: dict[str, object] | str, entry_type: str, message_role: str | None = None) -> TranscriptEntry:
    raw_line = raw_payload if isinstance(raw_payload, str) else json.dumps(raw_payload)
    return TranscriptEntry(
        entry_type=entry_type,
        message_role=message_role,
        raw_line=raw_line,
        byte_start=0,
        byte_end=max(len(raw_line), 1),
    )


@pytest.mark.parametrize(
    ("transcript_entry", "expected_parts"),
    [
        (
            entry(
                {
                    "type": "message",
                    "message": {"role": "user", "content": [{"type": "text", "text": "Find alpha   notes."}]},
                },
                "message",
                "user",
            ),
            ["message", "user", "Find alpha notes."],
        ),
        (
            entry(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "thinking", "thinking": "Considering beta options."}],
                    },
                },
                "message",
                "assistant",
            ),
            ["message", "assistant", "Considering beta options."],
        ),
        (
            entry(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "name": "read",
                                "arguments": {"path": "notes.md", "limit": 20},
                            },
                        ],
                    },
                },
                "message",
                "assistant",
            ),
            ["message", "assistant", "read", '{"limit":20,"path":"notes.md"}'],
        ),
        (
            entry(
                {"type": "custom_message", "customType": "notice", "content": "Gamma custom content."},
                "custom_message",
            ),
            ["custom_message", "notice", "Gamma custom content."],
        ),
        (
            entry(
                {"type": "custom", "customType": "title-state", "data": {"title": "Delta working title"}},
                "custom",
            ),
            ["custom", "title-state", "Delta working title"],
        ),
        (
            entry({"type": "compaction", "summary": "Epsilon summary text."}, "compaction"),
            ["compaction", "Epsilon summary text."],
        ),
        (
            entry({"type": "session_info", "name": "Zeta session"}, "session_info"),
            ["session_info", "Zeta session"],
        ),
        (
            entry({"type": "model_change", "provider": "anthropic", "modelId": "claude-test"}, "model_change"),
            ["model_change", "anthropic", "claude-test"],
        ),
        (
            entry({"type": "thinking_level_change", "thinkingLevel": "high"}, "thinking_level_change"),
            ["thinking_level_change", "high"],
        ),
        (
            entry({"type": "session", "cwd": "/tmp/project"}, "session"),
            ["session", "/tmp/project"],
        ),
    ],
)
def test_extract_search_text_for_useful_pi_shapes(
    transcript_entry: TranscriptEntry,
    expected_parts: list[str],
) -> None:
    search_text = extract_search_text(transcript_entry)

    assert search_text is not None
    for expected_part in expected_parts:
        assert expected_part in search_text


def test_extract_search_text_normalizes_whitespace() -> None:
    transcript_entry = entry(
        {
            "type": "message",
            "message": {"role": "user", "content": [{"type": "text", "text": "Alpha\n\t beta   gamma"}]},
        },
        "message",
        "user",
    )

    assert extract_search_text(transcript_entry) == "message user Alpha beta gamma"


@pytest.mark.parametrize(
    "transcript_entry",
    [
        entry({"type": "message", "message": {"role": "user", "content": []}}, "message", "user"),
        entry({"type": "custom_message", "customType": "empty", "content": "   "}, "custom_message"),
        entry({"type": "custom", "customType": "empty", "data": {"title": "   "}}, "custom"),
        entry({"type": "model_change"}, "model_change"),
        entry('{"type":"message",', "message"),
    ],
)
def test_extract_search_text_skips_entries_without_useful_text(transcript_entry: TranscriptEntry) -> None:
    assert extract_search_text(transcript_entry) is None


def test_index_transcript_is_idempotent_and_replaces_changed_content(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        transcript.entries.append(
            TranscriptEntry(
                entry_id="entry-1",
                entry_type="message",
                message_role="user",
                raw_line=json.dumps(
                    {
                        "type": "message",
                        "message": {"role": "user", "content": [{"type": "text", "text": "orchid original"}]},
                    },
                ),
                byte_start=0,
                byte_end=100,
            ),
        )
        session.add(transcript)
        session.flush()
        transcript_id = transcript.id
        entry_id = transcript.entries[0].id

        first_result = index_transcript(session, transcript_id)
        transcript.entries[0].raw_line = json.dumps(
            {
                "type": "message",
                "message": {"role": "user", "content": [{"type": "text", "text": "nebula replacement"}]},
            },
        )
        second_result = index_transcript(session, transcript_id)

    assert first_result.total_entries == 1
    assert first_result.indexed_entries == 1
    assert second_result.total_entries == 1
    assert second_result.indexed_entries == 1

    with database.engine.connect() as connection:
        row_count = connection.execute(text("SELECT count(*) FROM transcript_entries_fts")).scalar_one()
        old_matches = connection.execute(
            text("SELECT rowid FROM transcript_entries_fts WHERE transcript_entries_fts MATCH :query"),
            {"query": "orchid"},
        ).scalars().all()
        new_matches = connection.execute(
            text("SELECT rowid FROM transcript_entries_fts WHERE transcript_entries_fts MATCH :query"),
            {"query": "nebula"},
        ).scalars().all()

    assert row_count == 1
    assert old_matches == []
    assert new_matches == [entry_id]
