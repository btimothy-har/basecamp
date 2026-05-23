"""Deterministic interpretation quality checks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.db.constants import (
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
)
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    SessionInterpretationSnapshot,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation.contracts import is_claim_source_eligible
from pi_memory.interpretation.packets import SourceRef, build_interpretation_packet
from pi_memory.quality.contracts import (
    DERIVATION_STATUS_CURRENT,
    DERIVATION_STATUS_OUTDATED,
    DERIVATION_STATUS_SUPERSEDED,
    DETERMINISTIC_STATUS_FAILED,
    DETERMINISTIC_STATUS_NOT_APPLICABLE,
    DETERMINISTIC_STATUS_PASSED,
    FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH,
    FINDING_CODE_CITATION_ACTIVITY_MISSING,
    FINDING_CODE_CITATION_SOURCE_REF_UNKNOWN,
    FINDING_CODE_CITATION_TRANSCRIPT_ENTRY_MISSING,
    FINDING_CODE_CLAIM_MISSING_SOURCES,
    FINDING_CODE_CLAIM_SOURCE_REF_UNKNOWN,
    FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE,
    FINDING_CODE_CLAIMLESS_COMPLETED_INTERPRETATION,
    FINDING_CODE_EPISODE_INTERPRETATION_PARTIAL,
    FINDING_CODE_MISSING_INTERPRETATION_PAYLOAD,
    FINDING_CODE_MODEL_METADATA_MISSING,
    FINDING_CODE_PROMPT_VERSION_MISSING,
    FINDING_CODE_SNAPSHOT_OUTDATED,
    FINDING_CODE_SNAPSHOT_SUPERSEDED,
    FINDING_CODE_SOURCE_ORIGIN_INCOMPLETE,
    FINDING_CODE_SUMMARY_EMPTY,
    FINDING_CODE_TOOL_SUMMARY_INCOMPLETE,
    QUALITY_STATUS_FAILED,
    QUALITY_STATUS_NOT_ASSESSED,
    QUALITY_STATUS_REASON_BLOCKED,
    QUALITY_STATUS_REASON_DETERMINISTIC_FAILED,
    QUALITY_STATUS_REASON_OUTDATED,
    QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING,
    QUALITY_STATUS_REASON_SKIPPED,
    QUALITY_STATUS_REASON_SUPERSEDED,
    SEMANTIC_STATUS_NOT_ASSESSED,
    QualityFinding,
    QualityFindingReference,
    QualityReportDraft,
    compute_promotable,
)

_DETERMINISTIC_CHECK_VERSION = 1
_CRITICAL_SEVERITY = "critical"
_WARNING_SEVERITY = "warning"
_INFO_SEVERITY = "info"


def assess_deterministic_interpretation_quality(
    db_session: Session,
    snapshot: SessionInterpretationSnapshot,
) -> QualityReportDraft:
    """Assess locally provable quality dimensions for an interpretation snapshot."""
    derivation_status, derivation_findings = _derivation_status(db_session, snapshot)
    if snapshot.status == SESSION_INTERPRETATION_STATUS_BLOCKED:
        return _non_applicable_report(
            snapshot=snapshot,
            derivation_status=derivation_status,
            quality_reason=QUALITY_STATUS_REASON_BLOCKED,
            findings=derivation_findings,
        )
    if snapshot.status == SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES:
        return _non_applicable_report(
            snapshot=snapshot,
            derivation_status=derivation_status,
            quality_reason=QUALITY_STATUS_REASON_SKIPPED,
            findings=derivation_findings,
        )

    findings = [
        *derivation_findings,
        *_completed_integrity_findings(db_session, snapshot, derivation_status),
    ]
    deterministic_status = (
        DETERMINISTIC_STATUS_FAILED if _has_critical_findings(findings) else DETERMINISTIC_STATUS_PASSED
    )
    if deterministic_status == DETERMINISTIC_STATUS_FAILED:
        quality_reason = QUALITY_STATUS_REASON_DETERMINISTIC_FAILED
        quality_status = QUALITY_STATUS_FAILED
    elif derivation_status == DERIVATION_STATUS_SUPERSEDED:
        quality_reason = QUALITY_STATUS_REASON_SUPERSEDED
        quality_status = QUALITY_STATUS_NOT_ASSESSED
    elif derivation_status == DERIVATION_STATUS_OUTDATED:
        quality_reason = QUALITY_STATUS_REASON_OUTDATED
        quality_status = QUALITY_STATUS_NOT_ASSESSED
    else:
        quality_reason = QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING
        quality_status = QUALITY_STATUS_NOT_ASSESSED

    return _report(
        snapshot_status=snapshot.status,
        quality_status=quality_status,
        quality_reason=quality_reason,
        derivation_status=derivation_status,
        deterministic_status=deterministic_status,
        deterministic_findings=findings,
    )


def _non_applicable_report(
    *,
    snapshot: SessionInterpretationSnapshot,
    derivation_status: str,
    quality_reason: str,
    findings: list[QualityFinding],
) -> QualityReportDraft:
    return _report(
        snapshot_status=snapshot.status,
        quality_status=QUALITY_STATUS_NOT_ASSESSED,
        quality_reason=quality_reason,
        derivation_status=derivation_status,
        deterministic_status=DETERMINISTIC_STATUS_NOT_APPLICABLE,
        deterministic_findings=findings,
    )


def _report(
    *,
    snapshot_status: str,
    quality_status: str,
    quality_reason: str | None,
    derivation_status: str,
    deterministic_status: str,
    deterministic_findings: list[QualityFinding],
) -> QualityReportDraft:
    semantic_status = SEMANTIC_STATUS_NOT_ASSESSED
    return QualityReportDraft(
        quality_status=quality_status,
        quality_reason=quality_reason,
        derivation_status=derivation_status,
        deterministic_status=deterministic_status,
        semantic_status=semantic_status,
        promotable=compute_promotable(
            snapshot_status=snapshot_status,
            derivation_status=derivation_status,
            deterministic_status=deterministic_status,
            semantic_status=semantic_status,
            quality_status=quality_status,
        ),
        deterministic_findings=deterministic_findings,
        assessment_metadata={
            "deterministic_check_version": _DETERMINISTIC_CHECK_VERSION,
            "deterministic_finding_count": len(deterministic_findings),
        },
    )


def _derivation_status(
    db_session: Session,
    snapshot: SessionInterpretationSnapshot,
) -> tuple[str, list[QualityFinding]]:
    current_snapshot_id = db_session.scalar(
        select(SessionInterpretationSnapshot.id).where(
            SessionInterpretationSnapshot.session_id == snapshot.session_id,
        ),
    )
    if current_snapshot_id is not None and current_snapshot_id != snapshot.id:
        return DERIVATION_STATUS_SUPERSEDED, [
            _finding(
                code=FINDING_CODE_SNAPSHOT_SUPERSEDED,
                severity=_WARNING_SEVERITY,
                message="Interpretation snapshot is no longer the current session snapshot.",
                references=(_reference("snapshot", snapshot.id), _reference("snapshot", current_snapshot_id)),
            ),
        ]

    latest_run_id = _latest_analysis_run_id(db_session, snapshot.transcript_id)
    if latest_run_id is not None and snapshot.analysis_run_id != latest_run_id:
        return DERIVATION_STATUS_OUTDATED, [
            _finding(
                code=FINDING_CODE_SNAPSHOT_OUTDATED,
                severity=_WARNING_SEVERITY,
                message="Interpretation snapshot is older than the latest completed transcript analysis.",
                references=(_reference("snapshot", snapshot.id), _reference("analysis_run", latest_run_id)),
                details={
                    "snapshot_analysis_run_id": snapshot.analysis_run_id,
                    "latest_analysis_run_id": latest_run_id,
                },
            ),
        ]
    return DERIVATION_STATUS_CURRENT, []


def _latest_analysis_run_id(db_session: Session, transcript_id: int | None) -> int | None:
    if transcript_id is None:
        return None
    return db_session.scalar(
        select(AnalysisRun.id)
        .where(
            AnalysisRun.transcript_id == transcript_id,
            AnalysisRun.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            AnalysisRun.status == ANALYSIS_STATUS_COMPLETED,
        )
        .order_by(AnalysisRun.id.desc())
        .limit(1),
    )


def _completed_integrity_findings(
    db_session: Session,
    snapshot: SessionInterpretationSnapshot,
    derivation_status: str,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    interpretation = _mapping(snapshot.interpretation_json)
    if not interpretation:
        findings.append(
            _snapshot_finding(
                snapshot,
                FINDING_CODE_MISSING_INTERPRETATION_PAYLOAD,
                "Completed snapshot has no interpretation payload.",
            ),
        )
        return findings

    findings.extend(_identity_findings(snapshot, interpretation))
    findings.extend(_payload_findings(snapshot, interpretation))
    findings.extend(_metadata_findings(snapshot))
    findings.extend(_source_origin_findings(snapshot))
    findings.extend(_episode_interpretation_coverage_findings(snapshot, interpretation))
    if derivation_status == DERIVATION_STATUS_CURRENT:
        findings.extend(_citation_integrity_findings(db_session, snapshot, interpretation))
    return findings


def _identity_findings(
    snapshot: SessionInterpretationSnapshot,
    interpretation: Mapping[str, Any],
) -> list[QualityFinding]:
    expected = {
        "analysis_run_id": snapshot.analysis_run_id,
        "analyzed_through_entry_id": snapshot.analyzed_through_entry_id,
        "analyzed_through_byte_offset": snapshot.analyzed_through_byte_offset,
    }
    mismatches = [field for field, value in expected.items() if interpretation.get(field) != value]
    if not mismatches:
        return []
    return [
        _finding(
            code=FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH,
            severity=_CRITICAL_SEVERITY,
            message="Interpretation identity fields do not match the persisted snapshot.",
            references=(_reference("snapshot", snapshot.id),),
            details={"fields": ",".join(mismatches)},
        ),
    ]


def _payload_findings(
    snapshot: SessionInterpretationSnapshot,
    interpretation: Mapping[str, Any],
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    summary = interpretation.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        findings.append(
            _snapshot_finding(
                snapshot,
                FINDING_CODE_SUMMARY_EMPTY,
                "Completed interpretation summary is empty.",
            ),
        )

    claims = interpretation.get("claims")
    if not isinstance(claims, list) or not claims:
        if snapshot.claim_source_activity_count > 0:
            findings.append(
                _snapshot_finding(
                    snapshot,
                    FINDING_CODE_CLAIMLESS_COMPLETED_INTERPRETATION,
                    "Completed interpretation has no claims despite available claim sources.",
                ),
            )
        return findings

    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            findings.append(
                _claim_finding(index, FINDING_CODE_CLAIM_MISSING_SOURCES, "Interpretation claim is malformed."),
            )
            continue
        source_ref_ids = claim.get("source_ref_ids")
        if not isinstance(source_ref_ids, list) or not source_ref_ids:
            findings.append(
                _claim_finding(index, FINDING_CODE_CLAIM_MISSING_SOURCES, "Interpretation claim has no source refs."),
            )
    return findings


def _metadata_findings(snapshot: SessionInterpretationSnapshot) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    metadata = _mapping(snapshot.model_metadata_json)
    if not metadata.get("provider") or not metadata.get("model"):
        findings.append(
            _finding(
                code=FINDING_CODE_MODEL_METADATA_MISSING,
                severity=_CRITICAL_SEVERITY,
                message="Completed interpretation is missing model provider or model metadata.",
                references=(_reference("model_metadata", snapshot.id),),
            ),
        )
    if not isinstance(snapshot.prompt_version, str) or not snapshot.prompt_version.strip():
        findings.append(
            _finding(
                code=FINDING_CODE_PROMPT_VERSION_MISSING,
                severity=_CRITICAL_SEVERITY,
                message="Completed interpretation is missing a prompt version.",
                references=(_reference("prompt_version", snapshot.id),),
            ),
        )
    return findings


def _source_origin_findings(snapshot: SessionInterpretationSnapshot) -> list[QualityFinding]:
    origin_counts = _mapping(snapshot.origin_counts_json)
    unknown_count = origin_counts.get("unknown_activity_count")
    if isinstance(unknown_count, int) and unknown_count > 0:
        return [
            _finding(
                code=FINDING_CODE_SOURCE_ORIGIN_INCOMPLETE,
                severity=_CRITICAL_SEVERITY,
                message="Completed interpretation includes activity with unknown source origin.",
                references=(_reference("snapshot", snapshot.id),),
                details={"unknown_activity_count": unknown_count},
            ),
        ]
    return []


def _episode_interpretation_coverage_findings(
    snapshot: SessionInterpretationSnapshot,
    interpretation: Mapping[str, Any],
) -> list[QualityFinding]:
    coverage = _mapping(interpretation.get("aggregation"))
    if coverage.get("coverage_status") != "partial":
        return []
    return [
        _finding(
            code=FINDING_CODE_EPISODE_INTERPRETATION_PARTIAL,
            severity=_WARNING_SEVERITY,
            message="Session interpretation has partial episode coverage.",
            references=(_reference("snapshot", snapshot.id),),
            details=_episode_interpretation_coverage_details(coverage),
        ),
    ]


def _episode_interpretation_coverage_details(coverage: Mapping[str, Any]) -> dict[str, int | str]:
    keys = (
        "coverage_status",
        "total_episode_count",
        "claim_source_episode_count",
        "completed_episode_count",
        "skipped_episode_count",
        "failed_episode_count",
    )
    return {key: value for key in keys if isinstance((value := coverage.get(key)), int | str)}


def _citation_integrity_findings(
    db_session: Session,
    snapshot: SessionInterpretationSnapshot,
    interpretation: Mapping[str, Any],
) -> list[QualityFinding]:
    transcript = db_session.get(Transcript, snapshot.transcript_id) if snapshot.transcript_id is not None else None
    if transcript is None:
        return [
            _snapshot_finding(
                snapshot,
                FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH,
                "Interpretation transcript no longer exists.",
            ),
        ]
    packet = build_interpretation_packet(db_session, transcript, analysis_run_id=snapshot.analysis_run_id)
    source_refs = {
        source_ref.source_ref_id: source_ref
        for episode_packet in packet.episode_packets
        for source_ref in episode_packet.source_refs
    }
    findings: list[QualityFinding] = []
    findings.extend(_claim_source_findings(interpretation, source_refs))
    findings.extend(_citation_source_findings(db_session, snapshot, source_refs))
    return findings


def _claim_source_findings(
    interpretation: Mapping[str, Any],
    source_refs: Mapping[str, SourceRef],
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    claims = interpretation.get("claims")
    if not isinstance(claims, list):
        return findings
    for index, claim in enumerate(claims):
        if not isinstance(claim, Mapping):
            continue
        source_ref_ids = claim.get("source_ref_ids")
        if not isinstance(source_ref_ids, list):
            continue
        known_source_refs = []
        for source_ref_id in source_ref_ids:
            if not isinstance(source_ref_id, str):
                continue
            source_ref = source_refs.get(source_ref_id)
            if source_ref is None:
                findings.append(
                    _finding(
                        code=FINDING_CODE_CLAIM_SOURCE_REF_UNKNOWN,
                        severity=_CRITICAL_SEVERITY,
                        message="Interpretation claim cites an unknown source ref.",
                        references=(_reference("claim", index), _reference("source_ref", source_ref_id)),
                    ),
                )
            else:
                known_source_refs.append(source_ref)
        if known_source_refs and not any(is_claim_source_eligible(source_ref) for source_ref in known_source_refs):
            findings.append(
                _finding(
                    code=FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE,
                    severity=_CRITICAL_SEVERITY,
                    message="Interpretation claim lacks local or mixed claim-source support.",
                    references=(_reference("claim", index),),
                ),
            )
    return findings


def _citation_source_findings(
    db_session: Session,
    snapshot: SessionInterpretationSnapshot,
    source_refs: Mapping[str, SourceRef],
) -> list[QualityFinding]:
    citations = snapshot.citations_json if isinstance(snapshot.citations_json, list) else []
    findings: list[QualityFinding] = []
    for index, citation in enumerate(citations):
        if not isinstance(citation, Mapping):
            continue
        source_ref_id = citation.get("source_ref_id")
        if not isinstance(source_ref_id, str) or source_ref_id not in source_refs:
            findings.append(
                _finding(
                    code=FINDING_CODE_CITATION_SOURCE_REF_UNKNOWN,
                    severity=_CRITICAL_SEVERITY,
                    message="Interpretation citation points to an unknown source ref.",
                    references=(_reference("citation", index),),
                ),
            )
        activity_unit_id = citation.get("activity_unit_id")
        if isinstance(activity_unit_id, int):
            findings.extend(_activity_unit_findings(db_session, activity_unit_id, index))
        source_entry_row_ids = citation.get("source_entry_row_ids")
        if isinstance(source_entry_row_ids, list):
            findings.extend(_transcript_entry_findings(db_session, source_entry_row_ids, index))
        if citation.get("usage") == "claim" and not _citation_has_claim_source_origin(citation):
            findings.append(
                _finding(
                    code=FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE,
                    severity=_CRITICAL_SEVERITY,
                    message="Claim citation does not point to a local or mixed claim source.",
                    references=(_reference("citation", index),),
                ),
            )
    return findings


def _activity_unit_findings(db_session: Session, activity_unit_id: int, citation_index: int) -> list[QualityFinding]:
    activity = db_session.get(ActivityUnit, activity_unit_id)
    if activity is None:
        return [
            _finding(
                code=FINDING_CODE_CITATION_ACTIVITY_MISSING,
                severity=_CRITICAL_SEVERITY,
                message="Citation activity unit no longer exists.",
                references=(_reference("citation", citation_index), _reference("activity_unit", activity_unit_id)),
            ),
        ]
    if activity.activity_text_status != ACTIVITY_TEXT_STATUS_COMPLETED or activity.activity_text is None:
        return [
            _finding(
                code=FINDING_CODE_TOOL_SUMMARY_INCOMPLETE,
                severity=_CRITICAL_SEVERITY,
                message="Citation activity text is not complete.",
                references=(_reference("citation", citation_index), _reference("activity_unit", activity_unit_id)),
                details={"activity_text_status": activity.activity_text_status},
            ),
        ]
    return []


def _transcript_entry_findings(
    db_session: Session,
    source_entry_row_ids: list[Any],
    citation_index: int,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for row_id in source_entry_row_ids:
        if not isinstance(row_id, int):
            continue
        if db_session.get(TranscriptEntry, row_id) is None:
            findings.append(
                _finding(
                    code=FINDING_CODE_CITATION_TRANSCRIPT_ENTRY_MISSING,
                    severity=_CRITICAL_SEVERITY,
                    message="Citation source transcript entry no longer exists.",
                    references=(_reference("citation", citation_index), _reference("transcript_entry", row_id)),
                ),
            )
    return findings


def _citation_has_claim_source_origin(citation: Mapping[str, Any]) -> bool:
    return (
        citation.get("source_origin") in {SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED}
        and citation.get(
            "claim_source_allowed",
        )
        is True
    )


def _has_critical_findings(findings: list[QualityFinding]) -> bool:
    return any(finding.severity == _CRITICAL_SEVERITY for finding in findings)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _snapshot_finding(snapshot: SessionInterpretationSnapshot, code: str, message: str) -> QualityFinding:
    return _finding(
        code=code,
        severity=_CRITICAL_SEVERITY,
        message=message,
        references=(_reference("snapshot", snapshot.id),),
    )


def _claim_finding(claim_index: int, code: str, message: str) -> QualityFinding:
    return _finding(
        code=code,
        severity=_CRITICAL_SEVERITY,
        message=message,
        references=(_reference("claim", claim_index),),
    )


def _finding(
    *,
    code: str,
    severity: str,
    message: str,
    references: tuple[QualityFindingReference, ...] = (),
    details: dict[str, str | int | float | bool | None] | None = None,
) -> QualityFinding:
    return QualityFinding(
        code=code,
        severity=severity,
        message=message,
        references=list(references),
        details={} if details is None else details,
    )


def _reference(kind: str, identifier: int | str | None) -> QualityFindingReference:
    return QualityFindingReference(kind=kind, id="none" if identifier is None else str(identifier))
