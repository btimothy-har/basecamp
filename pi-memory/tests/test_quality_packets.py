from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pi_memory.analysis import analyze_transcript_structure
from pi_memory.db import (
    ActivityUnit,
    Database,
    MemorySession,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation import (
    INTERPRETATION_PROMPT_VERSION,
    INTERPRETATION_SCHEMA_VERSION,
    build_interpretation_packet,
    validate_interpretation_output,
)
from pi_memory.quality import QUALITY_ACTIVITY_TEXT_CHAR_LIMIT, build_quality_packet, quality_packet_prompt_data
from sqlalchemy import select

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path: Path) -> Database:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


def payload_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":")) + "\n"


def create_completed_snapshot(database: Database, *, text: str) -> tuple[int, str]:
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/repo")
        transcript = Transcript(path="/tmp/transcript.jsonl", session=memory_session)
        db_session.add(transcript)
        db_session.flush()
        raw_line = payload_line(
            {
                "type": "message",
                "id": "message-1",
                "message": {"role": "user", "content": text},
            },
        )
        entry = TranscriptEntry(
            transcript=transcript,
            entry_id="message-1",
            entry_type="message",
            message_role="user",
            timestamp=BASE_TIME + timedelta(seconds=1),
            raw_line=raw_line,
            byte_start=0,
            byte_end=len(raw_line.encode("utf-8")),
        )
        db_session.add(entry)
        transcript.cursor_offset = entry.byte_end
        transcript.file_size = entry.byte_end
        db_session.flush()
        analyze_transcript_structure(db_session, transcript)
        packet = build_interpretation_packet(db_session, transcript)
        source_ref_id = packet.episode_packets[0].source_refs[0].source_ref_id
        validated = validate_interpretation_output(
            {
                "analysis_run_id": packet.readiness.latest_analysis_run_id,
                "analyzed_through_entry_id": packet.readiness.analyzed_through_entry_id,
                "analyzed_through_byte_offset": packet.readiness.analyzed_through_byte_offset,
                "summary": "The session decided to add quality reports.",
                "claims": [
                    {
                        "source_ref_ids": [source_ref_id],
                        "kind": "decision",
                        "statement": "Add always-on interpretation quality reports.",
                        "confidence": 0.9,
                    },
                ],
                "open_questions": [],
                "citations": [{"source_ref_id": source_ref_id, "usage": "summary"}],
            },
            packet,
        )
        snapshot = SessionInterpretationSnapshot(
            session_id=transcript.session_id,
            transcript_id=transcript.id,
            analysis_run_id=packet.readiness.latest_analysis_run_id,
            status="completed",
            analyzed_through_entry_id=packet.readiness.analyzed_through_entry_id,
            analyzed_through_byte_offset=packet.readiness.analyzed_through_byte_offset,
            origin_counts_json=dict(packet.readiness.origin_counts),
            claim_source_activity_count=packet.readiness.claim_source_activity_count,
            interpretation_json=dict(validated.interpretation_json),
            citations_json=[dict(citation) for citation in validated.citations_json],
            model_metadata_json={"provider": "pi-memory", "model": "deterministic", "mode": "test"},
            prompt_version=INTERPRETATION_PROMPT_VERSION,
            schema_version=INTERPRETATION_SCHEMA_VERSION,
        )
        db_session.add(snapshot)
        db_session.flush()
        return snapshot.id, raw_line


def test_quality_packet_uses_bounded_activity_text_without_raw_lines(database: Database) -> None:
    snapshot_id, raw_line = create_completed_snapshot(database, text="QUALITY_PACKET_SECRET_SHOULD_BE_BOUNDED")

    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        packet = build_quality_packet(db_session, snapshot)
        prompt_data = quality_packet_prompt_data(packet)

    prompt_json = json.dumps(prompt_data, sort_keys=True)
    assert packet.readiness.can_assess_semantically is True
    assert packet.claim_count == 1
    assert packet.activities
    assert "raw_line" not in prompt_json
    assert raw_line not in prompt_json
    assert "QUALITY_PACKET_SECRET_SHOULD_BE_BOUNDED" in prompt_json


def test_quality_packet_bounds_activity_text(database: Database) -> None:
    snapshot_id, _raw_line = create_completed_snapshot(database, text="short")
    with database.session() as db_session:
        activity = db_session.scalar(select(ActivityUnit))
        assert activity is not None
        activity.activity_text = "x" * (QUALITY_ACTIVITY_TEXT_CHAR_LIMIT + 5)
        db_session.flush()

        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        packet = build_quality_packet(db_session, snapshot)

    activity_text = packet.activities[0].activity_text
    assert activity_text is not None
    assert activity_text.is_truncated is True
    assert activity_text.omitted_char_count == 5
