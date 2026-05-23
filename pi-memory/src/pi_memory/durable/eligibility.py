"""Deterministic quality-report eligibility evaluation for durable promotion."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pi_memory.db.constants import (
    SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED,
    SESSION_INTERPRETATION_DERIVATION_STATUS_SUPERSEDED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)
from pi_memory.db.models import SessionInterpretationQualityReport
from pi_memory.durable.contracts import QualityEligibilityEnvelope

_CLAIM_STATUS_WARNING_CODES = {
    "weakly_supported": "claim_weakly_supported",
    "overbroad": "claim_overbroad",
    "duplicate": "claim_duplicate",
}


_WARNING_CODE_BY_STATUS = {
    ("derivation_status", SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED): "derivation_outdated",
    ("derivation_status", SESSION_INTERPRETATION_DERIVATION_STATUS_SUPERSEDED): "derivation_superseded",
    ("deterministic_status", SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED): "deterministic_failed",
    ("semantic_status", SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED): "semantic_degraded",
    ("semantic_status", SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED): "semantic_assessment_failed",
    ("quality_status", SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED): "quality_degraded",
}


_SEMANTIC_STATUSES_REQUIRING_CLAIM_ASSESSMENT = {
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
}


def evaluate_claim_eligibility(
    report: SessionInterpretationQualityReport,
    claim_index: int,
) -> QualityEligibilityEnvelope:
    """Evaluate durable-promotion eligibility from persisted report and claim fields only."""
    snapshot = report.snapshot
    claims = _claims(snapshot.interpretation_json)
    claim = claims[claim_index] if 0 <= claim_index < len(claims) else None
    claim_assessment = find_claim_assessment(report, claim_index)
    block_reason = _block_reason(report, claim_index, claim, claim_assessment, len(claims))
    return QualityEligibilityEnvelope(
        quality_report_id=report.id,
        snapshot_id=snapshot.id,
        is_eligible=block_reason is None,
        block_reason=block_reason,
        warning_codes=extract_warning_codes(report, claim_assessment),
        quality_status=report.quality_status,
        semantic_status=report.semantic_status,
        deterministic_status=report.deterministic_status,
        derivation_status=report.derivation_status,
        promotable=report.promotable,
        claim_count=len(claims),
    )


def find_claim_assessment(
    report: SessionInterpretationQualityReport,
    claim_index: int,
) -> Mapping[str, Any] | None:
    """Return the persisted claim assessment for a claim index, if present."""
    assessments = report.claim_assessments_json
    if not isinstance(assessments, list):
        return None
    for assessment in assessments:
        if not isinstance(assessment, Mapping):
            continue
        persisted_claim_index = assessment.get("claim_index")
        if isinstance(persisted_claim_index, int) and not isinstance(persisted_claim_index, bool):
            if persisted_claim_index == claim_index:
                return assessment
    return None


def extract_warning_codes(
    report: SessionInterpretationQualityReport,
    claim_assessment: Mapping[str, Any] | None = None,
) -> list[str]:
    """Extract persisted warning codes without interpreting or recomputing quality."""
    warning_codes: list[str] = []
    _append_status_warnings(report, warning_codes)
    if claim_assessment is not None:
        _append_claim_assessment_warnings(claim_assessment, warning_codes)
    _append_finding_codes(report.deterministic_findings_json, warning_codes)
    _append_finding_codes(report.semantic_findings_json, warning_codes)
    return _dedupe_preserving_order(warning_codes)


def _block_reason(
    report: SessionInterpretationQualityReport,
    claim_index: int,
    claim: Mapping[str, Any] | None,
    claim_assessment: Mapping[str, Any] | None,
    claim_count: int,
) -> str | None:
    if report.snapshot.status != SESSION_INTERPRETATION_STATUS_COMPLETED:
        return "snapshot_not_completed"
    if report.promotable is not True:
        return "report_not_promotable"
    if claim_index < 0 or claim_index >= claim_count or claim is None:
        return "claim_missing"
    if not _source_ref_ids(claim):
        return "claim_source_refs_missing"
    if claim_assessment is None:
        if report.semantic_status in _SEMANTIC_STATUSES_REQUIRING_CLAIM_ASSESSMENT:
            return "claim_not_assessed"
        return None
    status = claim_assessment.get("status")
    if status == "unsupported":
        return "claim_unsupported"
    if status == "unclear":
        return "claim_too_vague"
    return None


def _append_status_warnings(report: SessionInterpretationQualityReport, warning_codes: list[str]) -> None:
    statuses = {
        "derivation_status": report.derivation_status,
        "deterministic_status": report.deterministic_status,
        "semantic_status": report.semantic_status,
        "quality_status": report.quality_status,
    }
    for key in (
        ("derivation_status", SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED),
        ("derivation_status", SESSION_INTERPRETATION_DERIVATION_STATUS_SUPERSEDED),
        ("deterministic_status", SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED),
        ("semantic_status", SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED),
        ("semantic_status", SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED),
        ("quality_status", SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED),
    ):
        field_name, status = key
        if statuses[field_name] == status:
            warning_codes.append(_WARNING_CODE_BY_STATUS[key])


def _append_claim_assessment_warnings(assessment: Mapping[str, Any], warning_codes: list[str]) -> None:
    status = assessment.get("status")
    if isinstance(status, str) and status in _CLAIM_STATUS_WARNING_CODES:
        warning_codes.append(_CLAIM_STATUS_WARNING_CODES[status])
    finding_codes = assessment.get("finding_codes")
    if isinstance(finding_codes, list):
        warning_codes.extend(code for code in finding_codes if isinstance(code, str) and code)


def _append_finding_codes(findings: Any, warning_codes: list[str]) -> None:
    if not isinstance(findings, list):
        return
    for finding in findings:
        if not isinstance(finding, Mapping):
            continue
        code = finding.get("code")
        if isinstance(code, str) and code:
            warning_codes.append(code)


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _claims(interpretation_json: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    claims = interpretation_json.get("claims")
    if not isinstance(claims, list):
        return []
    return [claim for claim in claims if isinstance(claim, Mapping)]


def _source_ref_ids(claim: Mapping[str, Any]) -> list[str]:
    source_ref_ids = claim.get("source_ref_ids")
    if not isinstance(source_ref_ids, list):
        return []
    return [source_ref_id for source_ref_id in source_ref_ids if isinstance(source_ref_id, str) and source_ref_id]


__all__ = [
    "evaluate_claim_eligibility",
    "extract_warning_codes",
    "find_claim_assessment",
]
