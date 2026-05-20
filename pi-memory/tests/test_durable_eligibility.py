from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pi_memory.durable.eligibility as eligibility_module
import pytest
from pi_memory.db import (
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    AnalysisRun,
    Database,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.durable import evaluate_claim_eligibility, find_claim_assessment


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
    claim_assessments: list[dict[str, Any]] | None = None,
    deterministic_findings: list[dict[str, Any]] | None = None,
    semantic_findings: list[dict[str, Any]] | None = None,
    snapshot_status: str = SESSION_INTERPRETATION_STATUS_COMPLETED,
    quality_status: str = SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    derivation_status: str = SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    deterministic_status: str = SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    semantic_status: str = SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    promotable: bool = True,
) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", repo_name="basecamp", worktree_label="wt-memory")
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        analysis_run = AnalysisRun(
            session=memory_session,
            transcript=transcript,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            activity_count=1,
        )
        default_claims = [
            {
                "source_ref_ids": ["source-1"],
                "kind": "decision",
                "statement": "Add deterministic durable eligibility.",
                "confidence": 0.93,
            },
        ]
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            analysis_run=analysis_run,
            status=snapshot_status,
            blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
            if snapshot_status == SESSION_INTERPRETATION_STATUS_BLOCKED
            else None,
            analyzed_through_byte_offset=123,
            claim_source_activity_count=1,
            interpretation_json={
                "summary": "Session summary.",
                "claims": claims if claims is not None else default_claims,
            },
            citations_json=[],
            prompt_version="interpretation-v1",
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=quality_status,
            quality_reason=None
            if quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
            else SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
            derivation_status=derivation_status,
            deterministic_status=deterministic_status,
            semantic_status=semantic_status,
            promotable=promotable,
            deterministic_findings_json=deterministic_findings if deterministic_findings is not None else [],
            semantic_findings_json=semantic_findings if semantic_findings is not None else [],
            claim_assessments_json=claim_assessments
            if claim_assessments is not None
            else [{"claim_index": 0, "status": "supported", "source_ref_ids": ["source-1"]}],
            prompt_version="quality-v1",
        )
        session.add(report)
        session.flush()
        return report.id


def load_report(database: Database, report_id: int) -> SessionInterpretationQualityReport:
    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        _ = report.snapshot.status
        return report


def test_supported_claim_is_eligible_and_copies_statuses(database: Database) -> None:
    report_id = create_quality_report(database)
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is True
    assert envelope.block_reason is None
    assert envelope.warning_codes == []
    assert envelope.quality_report_id == report_id
    assert envelope.snapshot_id == report.snapshot.id
    assert envelope.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
    assert envelope.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
    assert envelope.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert envelope.derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
    assert envelope.promotable is True
    assert envelope.claim_count == 1


def test_non_promotable_report_blocks_and_carries_warning_codes(database: Database) -> None:
    report_id = create_quality_report(
        database,
        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
        semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
        promotable=False,
        semantic_findings=[{"code": "semantic_finding", "severity": "warning", "message": "Persisted."}],
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is False
    assert envelope.block_reason == "report_not_promotable"
    assert envelope.warning_codes == ["semantic_degraded", "quality_degraded", "semantic_finding"]


def test_blocked_snapshot_blocks_first(database: Database) -> None:
    report_id = create_quality_report(
        database,
        snapshot_status=SESSION_INTERPRETATION_STATUS_BLOCKED,
        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
        semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
        promotable=False,
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is False
    assert envelope.block_reason == "snapshot_not_completed"


def test_claim_index_out_of_range_blocks_as_missing(database: Database) -> None:
    report_id = create_quality_report(database)
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 1)

    assert envelope.is_eligible is False
    assert envelope.block_reason == "claim_missing"


def test_empty_source_refs_blocks(database: Database) -> None:
    report_id = create_quality_report(
        database,
        claims=[
            {
                "source_ref_ids": [],
                "kind": "decision",
                "statement": "A claim without sources.",
                "confidence": 0.8,
            },
        ],
        claim_assessments=[{"claim_index": 0, "status": "supported", "source_ref_ids": []}],
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is False
    assert envelope.block_reason == "claim_source_refs_missing"


@pytest.mark.parametrize(
    "semantic_status", [SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED, SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED]
)
def test_missing_claim_assessment_with_passed_or_degraded_semantic_status_blocks(
    database: Database,
    semantic_status: str,
) -> None:
    report_id = create_quality_report(
        database,
        claim_assessments=[],
        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED
        if semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED
        else SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
        semantic_status=semantic_status,
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is False
    assert envelope.block_reason == "claim_not_assessed"


@pytest.mark.parametrize(
    ("assessment_status", "block_reason"),
    [("unsupported", "claim_unsupported"), ("unclear", "claim_too_vague")],
)
def test_unsupported_and_unclear_assessments_block(
    database: Database,
    assessment_status: str,
    block_reason: str,
) -> None:
    report_id = create_quality_report(
        database,
        claim_assessments=[{"claim_index": 0, "status": assessment_status, "source_ref_ids": ["source-1"]}],
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is False
    assert envelope.block_reason == block_reason


@pytest.mark.parametrize(
    ("assessment_status", "warning_code"),
    [
        ("weakly_supported", "claim_weakly_supported"),
        ("overbroad", "claim_overbroad"),
        ("duplicate", "claim_duplicate"),
    ],
)
def test_weak_overbroad_and_duplicate_assessments_remain_eligible_with_warnings(
    database: Database,
    assessment_status: str,
    warning_code: str,
) -> None:
    report_id = create_quality_report(
        database,
        claim_assessments=[{"claim_index": 0, "status": assessment_status, "source_ref_ids": ["source-1"]}],
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.is_eligible is True
    assert envelope.block_reason is None
    assert envelope.warning_codes == [warning_code]


def test_warning_codes_dedupe_persisted_codes_preserving_order(database: Database) -> None:
    report_id = create_quality_report(
        database,
        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
        derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED,
        deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED,
        semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
        claim_assessments=[
            {
                "claim_index": 0,
                "status": "weakly_supported",
                "finding_codes": ["shared", "claim_only", "semantic_degraded"],
                "source_ref_ids": ["source-1"],
            },
        ],
        deterministic_findings=[
            {"code": "shared", "severity": "warning", "message": "Duplicate."},
            {"code": "det_only", "severity": "warning", "message": "Deterministic."},
        ],
        semantic_findings=[
            {"code": "claim_only", "severity": "warning", "message": "Duplicate."},
            {"code": "sem_only", "severity": "warning", "message": "Semantic."},
        ],
    )
    report = load_report(database, report_id)

    envelope = evaluate_claim_eligibility(report, 0)

    assert envelope.warning_codes == [
        "derivation_outdated",
        "deterministic_failed",
        "semantic_degraded",
        "quality_degraded",
        "claim_weakly_supported",
        "shared",
        "claim_only",
        "det_only",
        "sem_only",
    ]


def test_find_claim_assessment_returns_matching_persisted_assessment(database: Database) -> None:
    report_id = create_quality_report(
        database,
        claims=[
            {"source_ref_ids": ["source-1"], "kind": "decision", "statement": "First.", "confidence": 0.8},
            {"source_ref_ids": ["source-2"], "kind": "knowledge", "statement": "Second.", "confidence": 0.7},
        ],
        claim_assessments=[
            {"claim_index": 1, "status": "duplicate", "source_ref_ids": ["source-2"]},
            {"claim_index": 0, "status": "supported", "source_ref_ids": ["source-1"]},
        ],
    )
    report = load_report(database, report_id)

    assessment = find_claim_assessment(report, 1)

    assert assessment is not None
    assert assessment["status"] == "duplicate"


def test_evaluation_is_read_only_and_has_no_external_seam_imports(database: Database) -> None:
    report_id = create_quality_report(database)
    with database.session() as session:
        report = session.get_one(SessionInterpretationQualityReport, report_id)
        assert not session.dirty

        evaluate_claim_eligibility(report, 0)

        assert not session.dirty
        assert session.is_modified(report) is False
        assert session.is_modified(report.snapshot) is False

    source = inspect.getsource(eligibility_module)
    forbidden_import_fragments = ["chroma", "projection", "provider", "pydantic_ai", "quality.assessor"]
    assert not any(fragment in source for fragment in forbidden_import_fragments)
