"""Durable-memory typed contracts for promotion pipelines."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from pi_memory.db.constants import (
    DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED,
    DURABLE_MEMORY_RELATION_TYPE_NOVEL,
    DURABLE_MEMORY_STATUS_ARCHIVED,
)

_DURABLE_TEXT_MAX_LENGTH = 2_000
_DURABLE_RATIONALE_MAX_LENGTH = 1_500
_DURABLE_REASON_MAX_LENGTH = 600
DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH = 400
_ELIGIBLE_WITH_BLOCK_REASON_MESSAGE = "eligible envelopes must not include a block reason"
_INELIGIBLE_WITHOUT_BLOCK_REASON_MESSAGE = "ineligible envelopes require a block reason"
_NOVEL_WITH_RELATED_MEMORY_MESSAGE = "novel relation assessments must not include related_memory_id"
_RELATED_MEMORY_REQUIRED_MESSAGE = "non-novel relation assessments require related_memory_id"
_ARCHIVE_TARGET_STATUS_MESSAGE = "archive decisions must target archived status"
_ARCHIVE_REASON_REQUIRED_MESSAGE = "archive decisions require archived_reason"
_SUPERSEDED_BY_REQUIRED_MESSAGE = "superseded archive decisions require superseded_by_id"
_NON_SUPERSEDED_BY_MESSAGE = "only superseded archive decisions can include superseded_by_id"
_NON_ARCHIVE_ARCHIVAL_FIELDS_MESSAGE = "non-archive decisions must not include archival fields"
_AUDIT_DETAIL_STRING_TOO_LONG = "audit detail strings must be at most 400 characters"

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BoundedString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=_DURABLE_TEXT_MAX_LENGTH),
]
BoundedRationale = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=_DURABLE_RATIONALE_MAX_LENGTH),
]
ReasonCode = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=_DURABLE_REASON_MAX_LENGTH)
]
ReferenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]

ClaimKind = Literal["decision", "constraint", "knowledge", "preference", "pattern", "action"]
MemoryScope = Literal["session", "cwd", "project", "global", "unknown"]
MetricLabel = Literal["pass", "warning", "fail"]
EligibilityBlockReason = Literal[
    "report_not_found",
    "snapshot_not_completed",
    "report_not_promotable",
    "claim_missing",
    "claim_not_assessed",
    "claim_unsupported",
    "claim_too_vague",
    "claim_transient",
    "claim_source_refs_missing",
]
DurableMemoryStatus = Literal["candidate", "promoted", "quarantined", "rejected", "archived"]
RelationType = Literal["novel", "duplicate", "reinforces", "refines", "conflicts", "supersedes", "stale_signal"]
ReducerAction = Literal["promote", "quarantine", "reject", "archive"]
ArchivedReason = Literal["superseded", "stale", "manually_retired", "source_invalidated"]
AuditEventType = Literal[
    "candidate_created",
    "eligibility_evaluated",
    "candidate_evaluated",
    "relation_assessed",
    "promoted",
    "quarantined",
    "rejected",
    "archived",
]
AuditDetailValue: TypeAlias = str | int | float | bool | None


class DurableMemoryCandidate(BaseModel):
    """Strict candidate extracted from one interpretation claim."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: int
    quality_report_id: int
    claim_index: int = Field(ge=0)
    claim_kind: ClaimKind
    statement: BoundedString
    confidence: float = Field(ge=0.0, le=1.0)
    source_ref_ids: list[ReferenceId] = Field(min_length=1)
    content_hash: NonEmptyString


class QualityEligibilityEnvelope(BaseModel):
    """Quality-report eligibility facts for one durable-memory candidate."""

    model_config = ConfigDict(extra="forbid")

    quality_report_id: int
    snapshot_id: int | None = None
    is_eligible: bool
    block_reason: EligibilityBlockReason | None = None
    warning_codes: list[NonEmptyString] = Field(default_factory=list)
    quality_status: str
    semantic_status: str
    deterministic_status: str
    derivation_status: str
    promotable: bool
    claim_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _block_reason_matches_eligibility(self) -> QualityEligibilityEnvelope:
        if self.is_eligible and self.block_reason is not None:
            raise ValueError(_ELIGIBLE_WITH_BLOCK_REASON_MESSAGE)
        if not self.is_eligible and self.block_reason is None:
            raise ValueError(_INELIGIBLE_WITHOUT_BLOCK_REASON_MESSAGE)
        return self


class CandidateMetricScore(BaseModel):
    """One bounded evaluator metric for candidate promotion."""

    model_config = ConfigDict(extra="forbid")

    score: float = Field(ge=0.0, le=1.0)
    label: MetricLabel
    reason: BoundedRationale


class CandidateEvaluationMetrics(BaseModel):
    """Evaluator metrics used by later durable-memory reducers."""

    model_config = ConfigDict(extra="forbid")

    is_supported: CandidateMetricScore
    is_vague: CandidateMetricScore
    is_durable: CandidateMetricScore
    is_transient: CandidateMetricScore
    is_overgeneralized: CandidateMetricScore
    scope_fit: CandidateMetricScore
    type_fit: CandidateMetricScore
    confidence: CandidateMetricScore


class CandidateEvaluationOutput(BaseModel):
    """Strict LLM evaluation output for one durable-memory candidate."""

    model_config = ConfigDict(extra="forbid")

    normalized_statement: BoundedString
    memory_type: ClaimKind
    scope: MemoryScope
    metrics: CandidateEvaluationMetrics
    overall_rationale: BoundedRationale | None = None


class RelationAssessmentOutput(BaseModel):
    """Strict relation assessment between a candidate and durable memory."""

    model_config = ConfigDict(extra="forbid")

    relation_type: RelationType
    related_memory_id: int | None = None
    similarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: BoundedRationale
    evidence_refs: list[ReferenceId] = Field(default_factory=list)

    @model_validator(mode="after")
    def _related_memory_matches_relation(self) -> RelationAssessmentOutput:
        if self.relation_type == DURABLE_MEMORY_RELATION_TYPE_NOVEL:
            if self.related_memory_id is not None:
                raise ValueError(_NOVEL_WITH_RELATED_MEMORY_MESSAGE)
        elif self.related_memory_id is None:
            raise ValueError(_RELATED_MEMORY_REQUIRED_MESSAGE)
        return self


class ReducerDecision(BaseModel):
    """Reducer status decision for a durable-memory candidate/item."""

    model_config = ConfigDict(extra="forbid")

    action: ReducerAction
    target_status: DurableMemoryStatus
    reason_code: ReasonCode
    rationale: BoundedRationale
    archived_reason: ArchivedReason | None = None
    superseded_by_id: int | None = None

    @model_validator(mode="after")
    def _archival_fields_match_action(self) -> ReducerDecision:
        if self.action == "archive":
            if self.target_status != DURABLE_MEMORY_STATUS_ARCHIVED:
                raise ValueError(_ARCHIVE_TARGET_STATUS_MESSAGE)
            if self.archived_reason is None:
                raise ValueError(_ARCHIVE_REASON_REQUIRED_MESSAGE)
            if self.archived_reason == DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED:
                if self.superseded_by_id is None:
                    raise ValueError(_SUPERSEDED_BY_REQUIRED_MESSAGE)
            elif self.superseded_by_id is not None:
                raise ValueError(_NON_SUPERSEDED_BY_MESSAGE)
            return self
        if self.archived_reason is not None or self.superseded_by_id is not None:
            raise ValueError(_NON_ARCHIVE_ARCHIVAL_FIELDS_MESSAGE)
        return self


class DurableMemoryAuditEventPayload(BaseModel):
    """Bounded audit payload for durable-memory state transitions."""

    model_config = ConfigDict(extra="forbid")

    event_type: AuditEventType
    from_status: DurableMemoryStatus | None = None
    to_status: DurableMemoryStatus | None = None
    reason_code: ReasonCode | None = None
    details: dict[NonEmptyString, AuditDetailValue] = Field(default_factory=dict, max_length=50)

    @field_validator("details")
    @classmethod
    def _validate_details(cls, details: Mapping[str, AuditDetailValue]) -> Mapping[str, AuditDetailValue]:
        for value in details.values():
            if isinstance(value, str) and len(value) > DURABLE_AUDIT_DETAIL_STRING_MAX_LENGTH:
                raise ValueError(_AUDIT_DETAIL_STRING_TOO_LONG)
        return details


__all__ = [
    "ArchivedReason",
    "AuditDetailValue",
    "AuditEventType",
    "BoundedRationale",
    "BoundedString",
    "CandidateEvaluationMetrics",
    "CandidateEvaluationOutput",
    "CandidateMetricScore",
    "ClaimKind",
    "DurableMemoryAuditEventPayload",
    "DurableMemoryCandidate",
    "DurableMemoryStatus",
    "EligibilityBlockReason",
    "MemoryScope",
    "MetricLabel",
    "NonEmptyString",
    "QualityEligibilityEnvelope",
    "ReasonCode",
    "ReducerAction",
    "ReducerDecision",
    "ReferenceId",
    "RelationAssessmentOutput",
    "RelationType",
]
