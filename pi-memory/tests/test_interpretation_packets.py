from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pi_memory.analysis import analyze_transcript_structure
from pi_memory.db import (
    ACTIVITY_KIND_SESSION_EVENT,
    ACTIVITY_KIND_TOOL_PAIR,
    ACTIVITY_TEXT_KIND_TOOL_SUMMARY,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    SOURCE_ORIGIN_INHERITED,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    ActivityUnit,
    Database,
    MemorySession,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation import build_interpretation_packet
from sqlalchemy import delete, func, select

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


def user_payload(entry_id: str, text: str = "hello") -> dict[str, Any]:
    return {
        "type": "message",
        "id": entry_id,
        "message": {"role": "user", "content": text},
    }


def session_payload(entry_id: str, parent_path: str | None = None) -> dict[str, Any]:
    payload = {"type": "session", "id": entry_id}
    if parent_path is not None:
        payload["parentSession"] = parent_path
    return payload


def assistant_tool_call_payload(entry_id: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": entry_id,
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "toolCall",
                    "id": "call-1",
                    "name": "bash",
                    "arguments": {"command": "printf long"},
                },
            ],
        },
    }


def tool_result_payload(entry_id: str, text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": entry_id,
        "message": {
            "role": "toolResult",
            "toolCallId": "call-1",
            "toolName": "bash",
            "content": [{"type": "text", "text": text}],
            "isError": False,
        },
    }


def create_transcript(
    db_session,
    *,
    stable_session_id: str = "pi-session-1",
    path: str = "/tmp/transcript.jsonl",
    payloads: list[dict[str, Any]] | None = None,
    parent_transcript_path: str | None = None,
    parent_transcript_id: int | None = None,
) -> Transcript:
    memory_session = MemorySession(
        session_id=stable_session_id,
        cwd="/repo",
        repo_name="repo",
        repo_root="/repo",
        worktree_label="main",
        worktree_path="/repo",
    )
    db_session.add(memory_session)
    db_session.flush()
    transcript = Transcript(
        session_id=memory_session.id,
        path=path,
        parent_transcript_path=parent_transcript_path,
        parent_transcript_id=parent_transcript_id,
        cursor_offset=0,
        file_size=0,
    )
    db_session.add(transcript)
    db_session.flush()
    offset = 0
    for index, payload in enumerate(payloads or [user_payload("message-1")], start=1):
        raw_line = payload_line(payload)
        entry = TranscriptEntry(
            transcript_id=transcript.id,
            entry_id=str(payload.get("id", f"entry-{index}")),
            parent_id=payload.get("parentId"),
            entry_type=str(payload.get("type", "message")),
            message_role=payload.get("message", {}).get("role"),
            timestamp=BASE_TIME + timedelta(seconds=index),
            raw_line=raw_line,
            byte_start=offset,
            byte_end=offset + len(raw_line.encode("utf-8")),
        )
        db_session.add(entry)
        offset = entry.byte_end
    transcript.cursor_offset = offset
    transcript.file_size = offset
    db_session.flush()
    return transcript


def test_ready_normal_transcript_after_phase_5a_analysis(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)
        result = analyze_transcript_structure(db_session, transcript)

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is True
    assert packet.readiness.can_call_model is True
    assert packet.readiness.should_skip_model is False
    assert packet.readiness.latest_analysis_run_id == result.analysis_run_id
    assert packet.readiness.claim_source_activity_count == 1
    assert packet.readiness.origin_counts["local_activity_count"] == 1
    assert len(packet.episode_packets) == 1
    assert packet.session_metadata["stable_session_id"] == "pi-session-1"
    assert packet.transcript_metadata["parent_transcript_path"] is None


def test_packet_readiness_uses_phase_5a_rows_when_snapshot_shells_are_deleted(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)
        result = analyze_transcript_structure(db_session, transcript)
        assert db_session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 1

        db_session.execute(delete(SessionSnapshotShell))
        db_session.flush()
        assert db_session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 0

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is True
    assert packet.readiness.latest_analysis_run_id == result.analysis_run_id
    assert packet.readiness.claim_source_activity_count == 1
    assert packet.readiness.activity_count == 1
    assert packet.readiness.episode_count == 1
    assert packet.readiness.manifest_count == 1
    assert len(packet.episode_packets) == 1


def test_requested_latest_analysis_id_builds_packet(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)
        result = analyze_transcript_structure(db_session, transcript)

        packet = build_interpretation_packet(db_session, transcript, analysis_run_id=result.analysis_run_id)

    assert packet.readiness.is_stale is False
    assert packet.readiness.is_ready is True
    assert packet.readiness.latest_analysis_run_id == result.analysis_run_id
    assert packet.readiness.requested_analysis_run_id == result.analysis_run_id
    assert len(packet.episode_packets) == 1


def test_unresolved_parent_blocks_readiness(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(
            db_session,
            payloads=[
                session_payload("session-1", parent_path="/tmp/missing-parent.jsonl"),
                user_payload("message-1"),
            ],
            parent_transcript_path="/tmp/missing-parent.jsonl",
        )
        analyze_transcript_structure(db_session, transcript)

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is False
    assert packet.readiness.blocked_reason == "parent_transcript_not_ingested"
    assert packet.readiness.can_call_model is False
    assert len(packet.episode_packets) == 1


def test_unknown_source_origin_blocks_readiness(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)
        analyze_transcript_structure(db_session, transcript)
        activity = db_session.scalar(select(ActivityUnit).where(ActivityUnit.transcript_id == transcript.id))
        activity.source_origin = SOURCE_ORIGIN_UNKNOWN
        db_session.flush()

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is False
    assert packet.readiness.blocked_reason == "source_origin_incomplete"
    assert packet.readiness.origin_counts["unknown_activity_count"] == 1
    assert packet.readiness.claim_source_activity_count == 0


def test_resolved_fork_counts_mixed_and_inherited_claim_sources(database: Database) -> None:
    with database.session() as db_session:
        parent = create_transcript(
            db_session,
            stable_session_id="pi-parent-session",
            path="/tmp/parent.jsonl",
            payloads=[user_payload("parent-user"), assistant_tool_call_payload("parent-call")],
        )
        transcript = create_transcript(
            db_session,
            stable_session_id="pi-child-session",
            path="/tmp/child.jsonl",
            parent_transcript_path="/tmp/parent.jsonl",
            parent_transcript_id=parent.id,
            payloads=[
                session_payload("child-session", parent_path="/tmp/parent.jsonl"),
                user_payload("parent-user"),
                assistant_tool_call_payload("parent-call"),
                tool_result_payload("child-result", "ok"),
                user_payload("child-user"),
            ],
        )
        analyze_transcript_structure(db_session, transcript)

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is True
    assert packet.readiness.origin_counts == {
        "local_activity_count": 2,
        "inherited_activity_count": 1,
        "mixed_activity_count": 1,
        "unknown_activity_count": 0,
    }
    assert packet.readiness.claim_source_activity_count == 1

    episode = packet.episode_packets[0]
    assert episode.origin_counts == packet.readiness.origin_counts
    assert episode.claim_source_activity_count == 1
    assert [activity.source_origin for activity in episode.included_activities] == [
        SOURCE_ORIGIN_LOCAL,
        SOURCE_ORIGIN_INHERITED,
        SOURCE_ORIGIN_MIXED,
        SOURCE_ORIGIN_LOCAL,
    ]
    assert [activity.claim_source_allowed for activity in episode.included_activities] == [False, False, False, True]
    assert episode.included_activities[2].activity_text_status == "pending"
    assert episode.included_activities[2].source_refs == ()


def test_no_claim_source_is_ready_but_skips_model(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session, payloads=[session_payload("session-1")])
        analyze_transcript_structure(db_session, transcript)

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is True
    assert packet.readiness.blocked_reason is None
    assert packet.readiness.claim_source_activity_count == 0
    assert packet.readiness.can_call_model is False
    assert packet.readiness.should_skip_model is True
    assert packet.episode_packets[0].included_activities[0].kind == ACTIVITY_KIND_SESSION_EVENT


def test_missing_phase_5a_analysis_blocks_readiness(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)

        packet = build_interpretation_packet(db_session, transcript)

    assert packet.readiness.is_ready is False
    assert packet.readiness.blocked_reason == "phase_5a_not_ready"
    assert packet.readiness.latest_analysis_run_id is None
    assert packet.episode_packets == ()


def test_requested_stale_analysis_id_marks_stale_and_builds_no_episode_packets(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)
        result = analyze_transcript_structure(db_session, transcript)
        stale_id = result.analysis_run_id - 1

        packet = build_interpretation_packet(db_session, transcript, analysis_run_id=stale_id)

    assert packet.readiness.is_stale is True
    assert packet.readiness.is_ready is False
    assert packet.readiness.can_call_model is False
    assert packet.readiness.blocked_reason is None
    assert packet.readiness.latest_analysis_run_id == result.analysis_run_id
    assert packet.readiness.requested_analysis_run_id == stale_id
    assert packet.readiness.origin_counts == {
        "local_activity_count": 0,
        "inherited_activity_count": 0,
        "mixed_activity_count": 0,
        "unknown_activity_count": 0,
    }
    assert packet.readiness.activity_count == 0
    assert packet.readiness.episode_count == 0
    assert packet.readiness.manifest_count == 0
    assert packet.episode_packets == ()


def test_requested_analysis_id_without_phase_5a_is_stale_and_not_ready(database: Database) -> None:
    with database.session() as db_session:
        transcript = create_transcript(db_session)

        packet = build_interpretation_packet(db_session, transcript, analysis_run_id=123)

    assert packet.readiness.is_stale is True
    assert packet.readiness.is_ready is False
    assert packet.readiness.blocked_reason == "phase_5a_not_ready"
    assert packet.readiness.latest_analysis_run_id is None
    assert packet.readiness.requested_analysis_run_id == 123
    assert packet.episode_packets == ()


def test_packet_shape_bounds_sources_and_preserves_manifest_ranges(database: Database) -> None:
    long_output = "TOOL_OUTPUT_" + ("x" * 2_000)
    payloads = [user_payload(f"message-{index}", text=f"hello {index}") for index in range(105)]
    payloads.extend(
        [
            assistant_tool_call_payload("assistant-tool"),
            tool_result_payload("tool-result", long_output),
        ],
    )
    with database.session() as db_session:
        transcript = create_transcript(db_session, payloads=payloads)
        analyze_transcript_structure(db_session, transcript)
        tool_row = db_session.scalar(
            select(ActivityUnit).where(
                ActivityUnit.transcript_id == transcript.id,
                ActivityUnit.kind == ACTIVITY_KIND_TOOL_PAIR,
            ),
        )
        assert tool_row is not None
        tool_row.activity_text = "Tool summary:\nThe bash tool produced a long output that was summarized."
        tool_row.activity_text_kind = ACTIVITY_TEXT_KIND_TOOL_SUMMARY
        tool_row.activity_text_status = ACTIVITY_TEXT_STATUS_COMPLETED
        tool_row.activity_text_metadata_json = {"producer": "test"}
        db_session.flush()

        packet = build_interpretation_packet(db_session, transcript)

    episode = packet.episode_packets[0]
    assert episode.included_ranges == ({"start_index": 0, "end_index": 105, "count": 106},)
    assert episode.omitted_ranges == ()
    assert episode.origin_counts["local_activity_count"] == 106
    assert episode.claim_source_activity_count == 106
    assert episode.tool_result_text_byte_count == len(long_output.encode("utf-8"))

    first_activity = episode.included_activities[0]
    assert first_activity.activity_text == "User message:\nhello 0"
    assert first_activity.source_refs[0].excerpts[0].text == "User message:\nhello 0"
    assert '{"type":"message"' not in first_activity.source_refs[0].excerpts[0].text

    tool_activity = episode.included_activities[-1]
    assert tool_activity.activity_text == "Tool summary:\nThe bash tool produced a long output that was summarized."
    assert tool_activity.claim_source_allowed is True
    assert tool_activity.source_origin == "local"
    assert tool_activity.result_text_byte_count == len(long_output.encode("utf-8"))
    assert tool_activity.source_refs

    source_ref = tool_activity.source_refs[0]
    assert source_ref.source_ref_id == (
        f"ar{packet.readiness.latest_analysis_run_id}:ep{episode.ordinal}:act{tool_activity.activity_index}:"
        f"entries{','.join(str(row_id) for row_id in source_ref.source_entry_row_ids)}"
    )
    assert source_ref.activity_unit_id == tool_activity.activity_unit_id
    assert source_ref.episode_id == episode.episode_id
    assert source_ref.episode_ordinal == episode.ordinal
    assert source_ref.activity_index == tool_activity.activity_index
    assert source_ref.activity_kind == "tool_pair"
    assert source_ref.claim_source_allowed is True
    assert len(source_ref.source_entry_row_ids) == 2
    assert all(excerpt.is_truncated or excerpt.original_char_count <= 500 for excerpt in source_ref.excerpts)
    assert max(len(excerpt.text) for excerpt in source_ref.excerpts) <= 500
    for excerpt in source_ref.excerpts:
        assert excerpt.omitted_char_count == excerpt.original_char_count - len(excerpt.text)
        assert excerpt.omitted_byte_count == excerpt.original_byte_count - len(excerpt.text.encode("utf-8"))
    assert source_ref.excerpts[0].text == "Tool summary:\nThe bash tool produced a long output that was summarized."
    assert long_output not in "".join(excerpt.text for excerpt in source_ref.excerpts)
    assert "toolResult" not in "".join(excerpt.text for excerpt in source_ref.excerpts)
    assert source_ref.receipt_metadata["tool_name"] == "bash"
    assert "source_entry_ids_by_origin" in source_ref.source_metadata
