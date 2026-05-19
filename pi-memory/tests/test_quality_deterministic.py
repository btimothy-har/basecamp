from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pi_memory.analysis import analyze_transcript_structure
from pi_memory.db import (
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_NOT_APPLICABLE,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION,
    SESSION_INTERPRETATION_QUALITY_REASON_DETERMINISTIC_INTEGRITY_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_OUTDATED_DERIVATION,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES,
    SESSION_INTERPRETATION_QUALITY_STATUS_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    AnalysisRun,
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
from pi_memory.quality import (
    FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH,
    FINDING_CODE_CITATION_SOURCE_REF_UNKNOWN,
    FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE,
    FINDING_CODE_EPISODE_INTERPRETATION_PARTIAL,
    FINDING_CODE_MODEL_METADATA_MISSING,
    FINDING_CODE_PROMPT_VERSION_MISSING,
    FINDING_CODE_SNAPSHOT_OUTDATED,
    assess_deterministic_interpretation_quality,
)

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


def create_transcript(db_session, *, text: str = "Remember the quality plan.") -> Transcript:
    memory_session = MemorySession(session_id="pi-session-1", cwd="/repo")
    db_session.add(memory_session)
    db_session.flush()
    transcript = Transcript(path="/tmp/transcript.jsonl", session=memory_session)
    db_session.add(transcript)
    db_session.flush()
    raw_line = payload_line(user_payload("message-1", text=text))
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
    return transcript


def interpretation_output(
    *,
    analysis_run_id: int,
    entry_id: int | None,
    byte_offset: int,
    source_ref_id: str,
) -> dict[str, Any]:
    return {
        "analysis_run_id": analysis_run_id,
        "analyzed_through_entry_id": entry_id,
        "analyzed_through_byte_offset": byte_offset,
        "summary": "The session captured a quality-reporting plan.",
        "claims": [
            {
                "source_ref_ids": [source_ref_id],
                "kind": "decision",
                "statement": "Add always-on quality reports after interpretation.",
                "confidence": 0.9,
            },
        ],
        "open_questions": [],
        "citations": [{"source_ref_id": source_ref_id, "usage": "summary"}],
    }


def create_completed_snapshot(database: Database, *, text: str = "Remember the quality plan.") -> int:
    with database.session() as db_session:
        transcript = create_transcript(db_session, text=text)
        analyze_transcript_structure(db_session, transcript)
        packet = build_interpretation_packet(db_session, transcript)
        source_ref_id = packet.episode_packets[0].source_refs[0].source_ref_id
        validated = validate_interpretation_output(
            interpretation_output(
                analysis_run_id=packet.readiness.latest_analysis_run_id or 0,
                entry_id=packet.readiness.analyzed_through_entry_id,
                byte_offset=packet.readiness.analyzed_through_byte_offset,
                source_ref_id=source_ref_id,
            ),
            packet,
        )
        snapshot = SessionInterpretationSnapshot(
            session_id=transcript.session_id,
            transcript_id=transcript.id,
            analysis_run_id=packet.readiness.latest_analysis_run_id,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
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
        return snapshot.id


def test_blocked_snapshot_gets_non_applicable_quality(database: Database) -> None:
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_BLOCKED,
            blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
        )
        db_session.add(snapshot)
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED
    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION
    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_NOT_APPLICABLE
    assert draft.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
    assert draft.promotable is False


def test_skipped_snapshot_gets_non_applicable_quality(database: Database) -> None:
    with database.session() as db_session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
        )
        db_session.add(snapshot)
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES
    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_NOT_APPLICABLE


def test_current_completed_snapshot_passes_deterministic_checks_and_waits_for_semantic_assessment(
    database: Database,
) -> None:
    snapshot_id = create_completed_snapshot(database)

    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert draft.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED
    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING
    assert draft.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
    assert draft.promotable is False
    assert draft.deterministic_findings_json == []


def test_partial_episode_coverage_adds_warning_without_failing_deterministic_checks(
    database: Database,
) -> None:
    snapshot_id = create_completed_snapshot(database)
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        interpretation = dict(snapshot.interpretation_json)
        interpretation["aggregation"] = {
            "aggregation_mode": "episode_claim_concat",
            "coverage_status": "partial",
            "total_episode_count": 2,
            "claim_source_episode_count": 2,
            "completed_episode_count": 1,
            "skipped_episode_count": 0,
            "failed_episode_count": 1,
        }
        snapshot.interpretation_json = interpretation

    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING
    assert draft.deterministic_findings[0].code == FINDING_CODE_EPISODE_INTERPRETATION_PARTIAL
    assert draft.deterministic_findings[0].severity == "warning"


def test_outdated_completed_snapshot_reports_derivation_separately(database: Database) -> None:
    snapshot_id = create_completed_snapshot(database)
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        db_session.add(
            AnalysisRun(
                session_id=snapshot.session_id,
                transcript_id=snapshot.transcript_id,
                status=ANALYSIS_STATUS_COMPLETED,
                analyzed_through_byte_offset=snapshot.analyzed_through_byte_offset,
            ),
        )
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED
    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_OUTDATED_DERIVATION
    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert draft.deterministic_findings_json[0]["code"] == FINDING_CODE_SNAPSHOT_OUTDATED


def test_unknown_citation_ref_fails_integrity(database: Database) -> None:
    snapshot_id = create_completed_snapshot(database)
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        citation = dict(snapshot.citations_json[0])
        citation["source_ref_id"] = "missing-ref"
        snapshot.citations_json = [citation]
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_FAILED
    assert draft.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_DETERMINISTIC_INTEGRITY_FAILED
    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED
    assert {finding["code"] for finding in draft.deterministic_findings_json} == {
        FINDING_CODE_CITATION_SOURCE_REF_UNKNOWN,
    }


def test_claim_without_eligible_local_or_mixed_citation_fails_integrity(database: Database) -> None:
    snapshot_id = create_completed_snapshot(database)
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        citation = dict(snapshot.citations_json[0])
        citation["source_origin"] = "inherited"
        citation["claim_source_allowed"] = False
        snapshot.citations_json = [citation]
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert draft.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED
    assert FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE in {
        finding["code"] for finding in draft.deterministic_findings_json
    }


def test_missing_metadata_prompt_and_identity_mismatch_fail_integrity(database: Database) -> None:
    snapshot_id = create_completed_snapshot(database)
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        interpretation = dict(snapshot.interpretation_json)
        interpretation["analysis_run_id"] = 999999
        snapshot.interpretation_json = interpretation
        snapshot.model_metadata_json = {}
        snapshot.prompt_version = None
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    codes = {finding["code"] for finding in draft.deterministic_findings_json}
    assert draft.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_FAILED
    assert FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH in codes
    assert FINDING_CODE_MODEL_METADATA_MISSING in codes
    assert FINDING_CODE_PROMPT_VERSION_MISSING in codes


def test_deterministic_findings_do_not_leak_raw_transcript_text(database: Database) -> None:
    snapshot_id = create_completed_snapshot(database, text="SECRET_TOKEN_SHOULD_NOT_LEAK")
    with database.session() as db_session:
        snapshot = db_session.get_one(SessionInterpretationSnapshot, snapshot_id)
        snapshot.model_metadata_json = {}
        db_session.flush()

        draft = assess_deterministic_interpretation_quality(db_session, snapshot)

    assert FINDING_CODE_MODEL_METADATA_MISSING in {finding["code"] for finding in draft.deterministic_findings_json}
    assert "SECRET_TOKEN_SHOULD_NOT_LEAK" not in json.dumps(draft.deterministic_findings_json)
