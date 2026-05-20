"""Durable-memory contracts and bounded packet builders."""

from pi_memory.durable.contracts import (
    CandidateEvaluationMetrics,
    CandidateEvaluationOutput,
    CandidateMetricScore,
    DurableMemoryAuditEventPayload,
    DurableMemoryCandidate,
    QualityEligibilityEnvelope,
    ReducerDecision,
    RelationAssessmentOutput,
)
from pi_memory.durable.packets import (
    DURABLE_ACTIVITY_TEXT_CHAR_LIMIT,
    DURABLE_METADATA_STRING_LIMIT,
    DURABLE_SOURCE_REF_LIMIT,
    BoundedText,
    DurableMemoryEvidencePacket,
    DurableMemoryPacketError,
    SourceRefEvidence,
    build_candidate_from_quality_report,
    build_durable_memory_evidence_packet,
)

__all__ = [
    "DURABLE_ACTIVITY_TEXT_CHAR_LIMIT",
    "DURABLE_METADATA_STRING_LIMIT",
    "DURABLE_SOURCE_REF_LIMIT",
    "BoundedText",
    "CandidateEvaluationMetrics",
    "CandidateEvaluationOutput",
    "CandidateMetricScore",
    "DurableMemoryAuditEventPayload",
    "DurableMemoryCandidate",
    "DurableMemoryEvidencePacket",
    "DurableMemoryPacketError",
    "QualityEligibilityEnvelope",
    "ReducerDecision",
    "RelationAssessmentOutput",
    "SourceRefEvidence",
    "build_candidate_from_quality_report",
    "build_durable_memory_evidence_packet",
]
