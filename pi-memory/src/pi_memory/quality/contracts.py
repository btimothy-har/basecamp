"""Quality assessment contracts for interpretation snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from pi_memory.db import (
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED,
    SESSION_INTERPRETATION_DERIVATION_STATUS_SUPERSEDED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_NOT_APPLICABLE,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION,
    SESSION_INTERPRETATION_QUALITY_REASON_DETERMINISTIC_INTEGRITY_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_OUTDATED_DERIVATION,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES,
    SESSION_INTERPRETATION_QUALITY_REASON_SUPERSEDED_SNAPSHOT,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)

QUALITY_ASSESSMENT_SCHEMA_VERSION = 1
_DETAIL_STRING_TOO_LONG = "detail strings must be at most 300 characters"
_HEALTHY_REASON_MESSAGE = "healthy quality reports must not have a quality reason"
_METADATA_STRING_TOO_LONG = "metadata strings must be at most 300 characters"
_NON_HEALTHY_REASON_MESSAGE = "non-healthy quality reports require a quality reason"

FINDING_CODE_SNAPSHOT_SUPERSEDED = "snapshot_superseded"
FINDING_CODE_SNAPSHOT_OUTDATED = "snapshot_outdated"
FINDING_CODE_MISSING_INTERPRETATION_PAYLOAD = "missing_interpretation_payload"
FINDING_CODE_SUMMARY_EMPTY = "summary_empty"
FINDING_CODE_CLAIMLESS_COMPLETED_INTERPRETATION = "claimless_completed_interpretation"
FINDING_CODE_CLAIM_MISSING_SOURCES = "claim_missing_sources"
FINDING_CODE_CLAIM_SOURCE_REF_UNKNOWN = "claim_source_ref_unknown"
FINDING_CODE_CLAIM_WITHOUT_ELIGIBLE_LOCAL_SOURCE = "claim_without_eligible_local_source"
FINDING_CODE_CITATION_SOURCE_REF_UNKNOWN = "citation_source_ref_unknown"
FINDING_CODE_CITATION_ACTIVITY_MISSING = "citation_activity_missing"
FINDING_CODE_CITATION_TRANSCRIPT_ENTRY_MISSING = "citation_transcript_entry_missing"
FINDING_CODE_SOURCE_ORIGIN_INCOMPLETE = "source_origin_incomplete"
FINDING_CODE_TOOL_SUMMARY_INCOMPLETE = "tool_summary_incomplete"
FINDING_CODE_MODEL_METADATA_MISSING = "model_metadata_missing"
FINDING_CODE_PROMPT_VERSION_MISSING = "prompt_version_missing"
FINDING_CODE_ANALYSIS_IDENTITY_MISMATCH = "analysis_identity_mismatch"
FINDING_CODE_QUALITY_ASSESSMENT_REFERENCE_UNRESOLVED = "quality_assessment_reference_unresolved"

QUALITY_BOUNDED_TEXT_MAX_LENGTH: Final = 500
QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH: Final = 20
QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH: Final = 50
QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH: Final = 20

BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=QUALITY_BOUNDED_TEXT_MAX_LENGTH),
]
FindingCode = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
MetadataKey = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ReferenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
MetadataValue: TypeAlias = str | int | float | bool | None
QualityFindingSeverity = Literal["critical", "warning", "info"]
QualityReferenceKind = Literal[
    "snapshot",
    "analysis_run",
    "interpretation",
    "claim",
    "citation",
    "source_ref",
    "activity_unit",
    "transcript_entry",
    "model_metadata",
    "prompt_version",
]
QualityStatus = Literal["healthy", "degraded", "failed", "not_assessed", "assessment_failed"]
QualityReason = Literal[
    "blocked_interpretation",
    "skipped_no_claim_sources",
    "outdated_derivation",
    "superseded_snapshot",
    "deterministic_integrity_failed",
    "semantic_degraded",
    "semantic_failed",
    "semantic_assessment_pending",
    "semantic_assessment_failed",
]
DerivationStatus = Literal["current", "outdated", "superseded"]
DeterministicStatus = Literal["passed", "failed", "not_applicable"]
SemanticStatus = Literal["passed", "degraded", "failed", "not_assessed", "assessment_failed"]
ClaimAssessmentStatus = Literal[
    "supported",
    "weakly_supported",
    "unsupported",
    "overbroad",
    "duplicate",
    "unclear",
]
HighSignalItemKind = Literal["decision", "constraint", "knowledge", "preference", "pattern", "action", "open_question"]


class QualityFindingReference(BaseModel):
    """Stable pointer to persisted quality evidence, never raw content."""

    model_config = ConfigDict(extra="forbid")

    kind: QualityReferenceKind
    id: ReferenceId


class QualityFinding(BaseModel):
    """Bounded quality finding safe for persistence and display."""

    model_config = ConfigDict(extra="forbid")

    code: FindingCode
    severity: QualityFindingSeverity
    message: BoundedText
    references: list[QualityFindingReference] = Field(default_factory=list, max_length=20)
    details: dict[MetadataKey, MetadataValue] = Field(default_factory=dict, max_length=20)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, details: Mapping[str, MetadataValue]) -> Mapping[str, MetadataValue]:
        for value in details.values():
            if isinstance(value, str) and len(value) > 300:
                raise ValueError(_DETAIL_STRING_TOO_LONG)
        return details


class QualityClaimAssessment(BaseModel):
    """Semantic assessment of one interpretation claim."""

    model_config = ConfigDict(extra="forbid")

    claim_index: int = Field(ge=0)
    status: ClaimAssessmentStatus
    finding_codes: list[FindingCode] = Field(default_factory=list, max_length=10)
    source_ref_ids: list[ReferenceId] = Field(default_factory=list, max_length=12)
    rationale: BoundedText | None = None


class MissingHighSignalItem(BaseModel):
    """High-signal session item the interpretation appears to miss."""

    model_config = ConfigDict(extra="forbid")

    kind: HighSignalItemKind
    description: BoundedText
    source_ref_ids: list[ReferenceId] = Field(default_factory=list, max_length=8)


class SemanticQualityAssessmentOutput(BaseModel):
    """Validated structured output from the semantic quality assessor."""

    model_config = ConfigDict(extra="forbid")

    semantic_status: Literal["passed", "degraded", "failed"]
    findings: list[QualityFinding] = Field(default_factory=list, max_length=QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH)
    claim_assessments: list[QualityClaimAssessment] = Field(
        default_factory=list, max_length=QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH
    )
    missing_high_signal_items: list[MissingHighSignalItem] = Field(
        default_factory=list,
        max_length=QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH,
    )
    overall_rationale: BoundedText | None = None


class QualityReportDraft(BaseModel):
    """Quality report fields ready for database persistence."""

    model_config = ConfigDict(extra="forbid")

    quality_status: QualityStatus
    quality_reason: QualityReason | None
    derivation_status: DerivationStatus = SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
    deterministic_status: DeterministicStatus = SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    semantic_status: SemanticStatus = SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
    promotable: bool = False
    deterministic_findings: list[QualityFinding] = Field(default_factory=list, max_length=50)
    semantic_findings: list[QualityFinding] = Field(default_factory=list, max_length=50)
    claim_assessments: list[QualityClaimAssessment] = Field(default_factory=list, max_length=100)
    missing_high_signal_items: list[MissingHighSignalItem] = Field(default_factory=list, max_length=50)
    model_metadata: dict[MetadataKey, MetadataValue] = Field(default_factory=dict, max_length=20)
    assessment_metadata: dict[MetadataKey, MetadataValue] = Field(default_factory=dict, max_length=20)
    prompt_version: ReferenceId | None = None
    schema_version: int = Field(default=QUALITY_ASSESSMENT_SCHEMA_VERSION, gt=0)

    @model_validator(mode="after")
    def _quality_reason_matches_status(self) -> QualityReportDraft:
        if self.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY and self.quality_reason is not None:
            raise ValueError(_HEALTHY_REASON_MESSAGE)
        if self.quality_status != SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY and self.quality_reason is None:
            raise ValueError(_NON_HEALTHY_REASON_MESSAGE)
        return self

    @field_validator("model_metadata", "assessment_metadata")
    @classmethod
    def _validate_metadata(cls, metadata: Mapping[str, MetadataValue]) -> Mapping[str, MetadataValue]:
        for value in metadata.values():
            if isinstance(value, str) and len(value) > 300:
                raise ValueError(_METADATA_STRING_TOO_LONG)
        return metadata

    @property
    def deterministic_findings_json(self) -> list[dict[str, Any]]:
        return [finding.model_dump(mode="json") for finding in self.deterministic_findings]

    @property
    def semantic_findings_json(self) -> list[dict[str, Any]]:
        return [finding.model_dump(mode="json") for finding in self.semantic_findings]

    @property
    def claim_assessments_json(self) -> list[dict[str, Any]]:
        return [assessment.model_dump(mode="json") for assessment in self.claim_assessments]

    @property
    def missing_high_signal_items_json(self) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.missing_high_signal_items]

    @property
    def model_metadata_json(self) -> dict[str, MetadataValue]:
        return dict(self.model_metadata)

    @property
    def assessment_metadata_json(self) -> dict[str, MetadataValue]:
        return dict(self.assessment_metadata)


def compute_promotable(
    *,
    snapshot_status: str,
    derivation_status: str,
    deterministic_status: str,
    semantic_status: str,
    quality_status: str,
) -> bool:
    """Return whether a report is eligible for later memory promotion."""
    has_safe_memory_substrate = (
        snapshot_status == SESSION_INTERPRETATION_STATUS_COMPLETED
        and derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
        and deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    )
    has_promotable_quality = (
        semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
        and quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
    ) or (
        semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED
        and quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED
    )
    return has_safe_memory_substrate and has_promotable_quality


QUALITY_STATUS_REASON_BLOCKED = SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION
QUALITY_STATUS_REASON_DETERMINISTIC_FAILED = SESSION_INTERPRETATION_QUALITY_REASON_DETERMINISTIC_INTEGRITY_FAILED
QUALITY_STATUS_REASON_OUTDATED = SESSION_INTERPRETATION_QUALITY_REASON_OUTDATED_DERIVATION
QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_FAILED = SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED
QUALITY_STATUS_REASON_SEMANTIC_ASSESSMENT_PENDING = SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_PENDING
QUALITY_STATUS_REASON_SEMANTIC_DEGRADED = SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED
QUALITY_STATUS_REASON_SEMANTIC_FAILED = SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_FAILED
QUALITY_STATUS_REASON_SKIPPED = SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES
QUALITY_STATUS_REASON_SUPERSEDED = SESSION_INTERPRETATION_QUALITY_REASON_SUPERSEDED_SNAPSHOT
QUALITY_STATUS_ASSESSMENT_FAILED = SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED
QUALITY_STATUS_DEGRADED = SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED
QUALITY_STATUS_FAILED = SESSION_INTERPRETATION_QUALITY_STATUS_FAILED
QUALITY_STATUS_HEALTHY = SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
QUALITY_STATUS_NOT_ASSESSED = SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED
DERIVATION_STATUS_CURRENT = SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
DERIVATION_STATUS_OUTDATED = SESSION_INTERPRETATION_DERIVATION_STATUS_OUTDATED
DERIVATION_STATUS_SUPERSEDED = SESSION_INTERPRETATION_DERIVATION_STATUS_SUPERSEDED
DETERMINISTIC_STATUS_FAILED = SESSION_INTERPRETATION_DETERMINISTIC_STATUS_FAILED
DETERMINISTIC_STATUS_NOT_APPLICABLE = SESSION_INTERPRETATION_DETERMINISTIC_STATUS_NOT_APPLICABLE
DETERMINISTIC_STATUS_PASSED = SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
SEMANTIC_STATUS_ASSESSMENT_FAILED = SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED
SEMANTIC_STATUS_DEGRADED = SESSION_INTERPRETATION_SEMANTIC_STATUS_DEGRADED
SEMANTIC_STATUS_FAILED = SESSION_INTERPRETATION_SEMANTIC_STATUS_FAILED
SEMANTIC_STATUS_NOT_ASSESSED = SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
SEMANTIC_STATUS_PASSED = SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
