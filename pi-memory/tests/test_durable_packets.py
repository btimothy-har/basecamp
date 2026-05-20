from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pi_memory.db import (
    ACTIVITY_KIND_USER_TEXT,
    ACTIVITY_TEXT_KIND_DETERMINISTIC,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SOURCE_ORIGIN_LOCAL,
    ActivityUnit,
    AnalysisRun,
    Database,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.durable import (
    DURABLE_ACTIVITY_TEXT_CHAR_LIMIT,
    DURABLE_SOURCE_REF_LIMIT,
    DurableMemoryPacketError,
    build_candidate_from_quality_report,
    build_durable_memory_evidence_packet,
)


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


def create_quality_report(
    database: Database,
    *,
    claims: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    promotable: bool = True,
    activity_text: str | None = "Evidence says to promote durable contracts.",
) -> tuple[int, int]:
    with database.session() as session:
        memory_session = MemorySession(
            session_id="pi-session-1",
            repo_name="basecamp",
            worktree_label="wt-memory",
        )
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        analysis_run = AnalysisRun(
            session=memory_session,
            transcript=transcript,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            activity_count=1,
        )
        activity = ActivityUnit(
            analysis_run=analysis_run,
            session=memory_session,
            transcript=transcript,
            ordinal=7,
            kind=ACTIVITY_KIND_USER_TEXT,
            byte_start=0,
            byte_end=50,
            source_origin=SOURCE_ORIGIN_LOCAL,
            activity_text=activity_text,
            activity_text_kind=ACTIVITY_TEXT_KIND_DETERMINISTIC,
            activity_text_status=ACTIVITY_TEXT_STATUS_COMPLETED,
        )
        session.add(activity)
        session.flush()
        source_ref_ids = ["source-1"]
        default_claims = [
            {
                "source_ref_ids": source_ref_ids,
                "kind": "decision",
                "statement": "Add durable-memory packet contracts.",
                "confidence": 0.93,
            },
        ]
        default_citations = [
            {
                "usage": "claim",
                "claim_index": 0,
                "claim_kind": "decision",
                "source_ref_id": "source-1",
                "activity_unit_id": activity.id,
                "episode_ordinal": 2,
                "activity_kind": ACTIVITY_KIND_USER_TEXT,
                "activity_index": 7,
                "source_origin": SOURCE_ORIGIN_LOCAL,
                "metadata_note": "safe metadata",
            },
        ]
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            analysis_run=analysis_run,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            claim_source_activity_count=1,
            interpretation_json={
                "summary": "Session summary.",
                "claims": claims if claims is not None else default_claims,
            },
            citations_json=citations if citations is not None else default_citations,
            prompt_version="interpretation-v1",
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
            if promotable
            else SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
            quality_reason=None if promotable else SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
            derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
            semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
            if promotable
            else SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
            promotable=promotable,
            claim_assessments_json=[
                {"claim_index": 0, "status": "supported", "source_ref_ids": source_ref_ids},
            ],
            prompt_version="quality-v1",
        )
        session.add(report)
        session.flush()
        return report.id, snapshot.id


def expected_content_hash(claim: dict[str, Any]) -> str:
    payload = {
        "kind": claim["kind"],
        "statement": claim["statement"],
        "confidence": float(claim["confidence"]),
        "source_ref_ids": claim["source_ref_ids"],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def test_evidence_packet_rejects_missing_report(database: Database) -> None:
    with database.session() as session:
        with pytest.raises(DurableMemoryPacketError):
            build_durable_memory_evidence_packet(session, report_id=9999, claim_index=0)


def test_candidate_builder_creates_candidate_with_stable_content_hash(database: Database) -> None:
    claim = {
        "source_ref_ids": ["source-1"],
        "kind": "decision",
        "statement": "Add durable-memory packet contracts.",
        "confidence": 0.93,
    }
    report_id, snapshot_id = create_quality_report(database, claims=[claim])

    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        candidate = build_candidate_from_quality_report(report, 0)
        candidate_again = build_candidate_from_quality_report(report, 0)

    assert candidate.snapshot_id == snapshot_id
    assert candidate.quality_report_id == report_id
    assert candidate.claim_index == 0
    assert candidate.claim_kind == "decision"
    assert candidate.source_ref_ids == ["source-1"]
    assert candidate.content_hash == expected_content_hash(claim)
    assert candidate_again.content_hash == candidate.content_hash


def test_evidence_packet_includes_canonical_source_refs_and_bounded_activity_text(database: Database) -> None:
    long_text = "x" * (DURABLE_ACTIVITY_TEXT_CHAR_LIMIT + 9)
    report_id, snapshot_id = create_quality_report(database, activity_text=long_text)

    with database.session() as session:
        packet = build_durable_memory_evidence_packet(session, report_id, 0)

    evidence = packet.source_evidence[0]
    assert packet.session_id == "pi-session-1"
    assert packet.repo_name == "basecamp"
    assert packet.worktree_label == "wt-memory"
    assert packet.snapshot_id == snapshot_id
    assert packet.quality_report_id == report_id
    assert packet.candidate.source_ref_ids == ["source-1"]
    assert packet.eligibility.is_eligible is True
    assert evidence.source_ref_id == "source-1"
    assert evidence.source_origin == SOURCE_ORIGIN_LOCAL
    assert evidence.activity_kind == ACTIVITY_KIND_USER_TEXT
    assert evidence.activity_ordinal == 7
    assert evidence.episode_ordinal == 2
    assert evidence.activity_text is not None
    assert evidence.activity_text.text == "x" * DURABLE_ACTIVITY_TEXT_CHAR_LIMIT
    assert evidence.activity_text.is_truncated is True
    assert evidence.activity_text.omitted_char_count == 9
    assert evidence.citation_metadata["source_ref_id"] == "source-1"


def test_evidence_packet_caps_source_refs_and_reports_omitted_count(database: Database) -> None:
    source_ref_ids = [f"source-{index}" for index in range(25)]
    claims = [
        {
            "source_ref_ids": source_ref_ids,
            "kind": "knowledge",
            "statement": "Many sources support this durable fact.",
            "confidence": 0.82,
        },
    ]
    citations = [
        {"usage": "claim", "claim_index": 0, "source_ref_id": source_ref_id, "source_origin": SOURCE_ORIGIN_LOCAL}
        for source_ref_id in source_ref_ids
    ]
    report_id, _snapshot_id = create_quality_report(database, claims=claims, citations=citations)

    with database.session() as session:
        packet = build_durable_memory_evidence_packet(session, report_id, 0)

    assert len(packet.source_evidence) == DURABLE_SOURCE_REF_LIMIT
    assert packet.omitted_source_count == 5
    assert [evidence.source_ref_id for evidence in packet.source_evidence] == source_ref_ids[:DURABLE_SOURCE_REF_LIMIT]
    assert packet.candidate.source_ref_ids == source_ref_ids


@pytest.mark.parametrize(
    ("claims", "claim_index"),
    [
        ([{"source_ref_ids": ["source-1"], "kind": "decision", "statement": "A claim.", "confidence": 0.8}], 1),
        ([{"source_ref_ids": [], "kind": "decision", "statement": "A claim.", "confidence": 0.8}], 0),
    ],
)
def test_missing_claim_or_source_refs_raises_packet_error(
    database: Database,
    claims: list[dict[str, Any]],
    claim_index: int,
) -> None:
    report_id, _snapshot_id = create_quality_report(database, claims=claims)

    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        with pytest.raises(DurableMemoryPacketError):
            build_candidate_from_quality_report(report, claim_index)
        with pytest.raises(DurableMemoryPacketError):
            build_durable_memory_evidence_packet(session, report_id, claim_index)


def test_invalid_claim_confidence_raises_packet_error(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(
        database,
        claims=[
            {
                "source_ref_ids": ["source-1"],
                "kind": "decision",
                "statement": "A claim with invalid confidence.",
                "confidence": True,
            },
        ],
    )

    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        with pytest.raises(DurableMemoryPacketError):
            build_candidate_from_quality_report(report, 0)


def test_blocked_snapshot_builds_ineligible_packet_without_recomputing_checks(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)

    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        report.snapshot.status = SESSION_INTERPRETATION_STATUS_BLOCKED
        report.snapshot.blocked_reason = SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
        packet = build_durable_memory_evidence_packet(session, report_id, 0)

    assert packet.eligibility.is_eligible is False
    assert packet.eligibility.block_reason == "snapshot_not_completed"
    assert packet.candidate.statement == "Add durable-memory packet contracts."


def test_non_promotable_report_builds_ineligible_packet_without_recomputing_checks(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database, promotable=False)

    with database.session() as session:
        packet = build_durable_memory_evidence_packet(session, report_id, 0)

    assert packet.eligibility.is_eligible is False
    assert packet.eligibility.block_reason == "report_not_promotable"
    assert packet.eligibility.promotable is False
    assert packet.eligibility.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED
    assert packet.eligibility.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED
    assert packet.eligibility.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert packet.candidate.statement == "Add durable-memory packet contracts."
