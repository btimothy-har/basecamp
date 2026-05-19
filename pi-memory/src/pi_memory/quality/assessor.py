"""Quality assessment seam for pi-memory."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, ValidationError

try:
    from pydantic_ai import Agent as PydanticAIAgent
except ImportError:
    PydanticAIAgent = None

from pi_memory.quality.contracts import (
    FINDING_CODE_QUALITY_ASSESSMENT_REFERENCE_UNRESOLVED,
    QUALITY_ASSESSMENT_SCHEMA_VERSION,
    QUALITY_BOUNDED_TEXT_MAX_LENGTH,
    QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH,
    QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH,
    QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH,
    QUALITY_STATUS_DEGRADED,
    QUALITY_STATUS_FAILED,
    QUALITY_STATUS_HEALTHY,
    QUALITY_STATUS_REASON_SEMANTIC_DEGRADED,
    QUALITY_STATUS_REASON_SEMANTIC_FAILED,
    SEMANTIC_STATUS_DEGRADED,
    SEMANTIC_STATUS_FAILED,
    SEMANTIC_STATUS_PASSED,
    QualityFinding,
    QualityFindingReference,
    QualityReportDraft,
    SemanticQualityAssessmentOutput,
    compute_promotable,
)
from pi_memory.quality.packets import (
    QualityPacket,
    QualitySourceRefAliases,
    build_quality_source_ref_aliases,
    quality_packet_prompt_data,
)

QUALITY_ASSESSMENT_PROMPT_VERSION = "phase5c-semantic-quality-assessment-v2"
PYDANTIC_AI_QUALITY_ASSESSOR_MODE = "pydantic-ai"
DETERMINISTIC_QUALITY_ASSESSOR_MODE = "deterministic"
DETERMINISTIC_QUALITY_ASSESSOR_MODEL = "deterministic-quality-assessor-v1"
_PYDANTIC_AI_ERROR_MESSAGE = "PydanticAI quality assessment failed"
_PYDANTIC_AI_DEPENDENCY_ERROR_MESSAGE = "pydantic-ai is required for PydanticAIQualityAssessor"
_PACKET_NOT_READY_MESSAGE = "Quality packet is not ready for semantic assessment"
_SCHEMA_ERROR_MESSAGE = "Quality assessment output does not match the required schema"
_UNKNOWN_SOURCE_REF_MESSAGE = "Quality assessment output cites an unknown source_ref_id"
_UNKNOWN_CLAIM_INDEX_MESSAGE = "Quality assessment output cites an unknown claim index"
_QUALITY_METADATA_TEXT_MAX_LENGTH = 300
_REFERENCE_DEFECTS_MAX_LENGTH = 20
_REFERENCE_DEFECT_ID_MAX_LENGTH = 160
_REFERENCE_DEFECT_PATH_MAX_LENGTH = 160
_UNRESOLVED_REFERENCE_FINDING_MESSAGE = (
    "Quality assessor cited unresolved source refs; invalid quality references were omitted."
)
_SOURCE_REF_ALIAS_PATTERN = re.compile(r"(?<![A-Za-z0-9_])s\d{4}(?![A-Za-z0-9_])")

AgentFactory = Callable[..., Any]


@dataclass(frozen=True)
class QualityAssessmentResult:
    """Semantic quality assessment output and model metadata."""

    output: SemanticQualityAssessmentOutput
    model_metadata: Mapping[str, Any]
    prompt_version: str
    schema_version: int = QUALITY_ASSESSMENT_SCHEMA_VERSION


@dataclass(frozen=True)
class QualityReferenceDefect:
    """Unresolved quality-assessor source reference omitted during validation."""

    field_path: str
    reference_id: str


@dataclass(frozen=True)
class ValidatedQualityAssessment:
    """Validated semantic assessment with recoverable reference defects."""

    output: SemanticQualityAssessmentOutput
    reference_defects: tuple[QualityReferenceDefect, ...] = ()
    omitted_reference_defect_count: int = 0

    @property
    def reference_defect_count(self) -> int:
        return len(self.reference_defects) + self.omitted_reference_defect_count


class QualityAssessor(Protocol):
    """Assesses semantic quality packets."""

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        """Assess a quality packet synchronously."""
        ...

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        """Assess a quality packet asynchronously."""
        ...


class QualityAssessmentError(Exception):
    """Base error for quality assessment failures."""


class QualityAssessmentUnavailableError(QualityAssessmentError):
    """Raised when a packet cannot be semantically assessed."""

    @classmethod
    def packet_not_ready(cls, reason: str | None) -> QualityAssessmentUnavailableError:
        suffix = "" if reason is None else f": {reason}"
        return cls(f"{_PACKET_NOT_READY_MESSAGE}{suffix}")


class QualityAssessmentValidationError(QualityAssessmentError):
    """Raised when semantic assessment output is invalid for a packet."""

    @classmethod
    def schema_error(cls) -> QualityAssessmentValidationError:
        return cls(_SCHEMA_ERROR_MESSAGE)

    @classmethod
    def unknown_source_ref(cls, source_ref_id: str) -> QualityAssessmentValidationError:
        return cls(f"{_UNKNOWN_SOURCE_REF_MESSAGE}: {source_ref_id}")

    @classmethod
    def unknown_claim_index(cls, claim_index: int) -> QualityAssessmentValidationError:
        return cls(f"{_UNKNOWN_CLAIM_INDEX_MESSAGE}: {claim_index}")


class PydanticAIQualityAssessmentError(QualityAssessmentError):
    """Raised when a PydanticAI provider call fails during quality assessment."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_ERROR_MESSAGE)


class PydanticAIDependencyError(QualityAssessmentError):
    """Raised when PydanticAI is unavailable for quality assessment."""

    def __init__(self) -> None:
        super().__init__(_PYDANTIC_AI_DEPENDENCY_ERROR_MESSAGE)


class PydanticAIQualityAssessor:
    """PydanticAI-backed semantic quality assessor."""

    def __init__(
        self,
        model: str,
        *,
        prompt_version: str = QUALITY_ASSESSMENT_PROMPT_VERSION,
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self.model = model
        self.prompt_version = prompt_version
        self._agent = _create_pydantic_ai_agent(model, SemanticQualityAssessmentOutput, agent_factory)

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        """Assess a quality packet using PydanticAI synchronously."""
        _validate_packet_ready_for_assessment(packet)
        prompt = _render_quality_assessment_prompt(packet)
        try:
            run_result = self._agent.run_sync(prompt)
            validated = validate_quality_assessment_result(_extract_quality_assessment_output(run_result), packet)
        except Exception as error:
            raise PydanticAIQualityAssessmentError() from error
        return _quality_report_from_semantic_output(
            packet=packet,
            validated=validated,
            model_metadata=_pydantic_ai_model_metadata(self.model),
            prompt_version=self.prompt_version,
        )

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        """Assess a quality packet using one async PydanticAI call."""
        _validate_packet_ready_for_assessment(packet)
        prompt = _render_quality_assessment_prompt(packet)
        try:
            run_result = await _run_pydantic_ai_agent(self._agent, prompt)
            validated = validate_quality_assessment_result(_extract_quality_assessment_output(run_result), packet)
        except Exception as error:
            raise PydanticAIQualityAssessmentError() from error
        return _quality_report_from_semantic_output(
            packet=packet,
            validated=validated,
            model_metadata=_pydantic_ai_model_metadata(self.model),
            prompt_version=self.prompt_version,
        )


@dataclass(frozen=True)
class DeterministicQualityAssessor:
    """Deterministic test/development assessor with no model dependencies."""

    prompt_version: str = QUALITY_ASSESSMENT_PROMPT_VERSION
    model_metadata: Mapping[str, Any] | None = None

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        """Produce a deterministic healthy semantic assessment."""
        _validate_packet_ready_for_assessment(packet)
        output = SemanticQualityAssessmentOutput(
            semantic_status=SEMANTIC_STATUS_PASSED,
            findings=[],
            claim_assessments=[],
            missing_high_signal_items=[],
            overall_rationale="Deterministic assessment found no semantic quality defects.",
        )
        return _quality_report_from_semantic_output(
            packet=packet,
            validated=ValidatedQualityAssessment(output=output),
            model_metadata=self.model_metadata if self.model_metadata is not None else _deterministic_model_metadata(),
            prompt_version=self.prompt_version,
        )

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        """Produce a deterministic healthy semantic assessment asynchronously."""
        return self.assess(packet)


def validate_quality_assessment_result(
    output: SemanticQualityAssessmentOutput | Mapping[str, Any],
    packet: QualityPacket,
) -> ValidatedQualityAssessment:
    """Validate semantic assessment output against its quality packet."""
    model = _coerce_quality_assessment_output(output)
    model = _canonicalize_quality_assessment_source_refs(model, build_quality_source_ref_aliases(packet))
    _validate_claim_indexes(model, packet)
    return _omit_unresolved_quality_references(model, packet)


def validate_quality_assessment_output(
    output: SemanticQualityAssessmentOutput | Mapping[str, Any],
    packet: QualityPacket,
) -> SemanticQualityAssessmentOutput:
    """Validate semantic assessment output and return its sanitized payload."""
    return validate_quality_assessment_result(output, packet).output


def _coerce_quality_assessment_output(
    output: SemanticQualityAssessmentOutput | Mapping[str, Any],
) -> SemanticQualityAssessmentOutput:
    try:
        return (
            output
            if isinstance(output, SemanticQualityAssessmentOutput)
            else SemanticQualityAssessmentOutput.model_validate(output)
        )
    except ValidationError as error:
        raise QualityAssessmentValidationError.schema_error() from error


def _validate_claim_indexes(output: SemanticQualityAssessmentOutput, packet: QualityPacket) -> None:
    for assessment in output.claim_assessments:
        if assessment.claim_index >= packet.claim_count:
            raise QualityAssessmentValidationError.unknown_claim_index(assessment.claim_index)


def _omit_unresolved_quality_references(
    output: SemanticQualityAssessmentOutput,
    packet: QualityPacket,
) -> ValidatedQualityAssessment:
    valid_source_ref_ids = packet.source_ref_ids
    reference_defects: list[QualityReferenceDefect] = []
    claim_assessments = []
    missing_high_signal_items = []
    findings = []
    changed = False

    for assessment_index, assessment in enumerate(output.claim_assessments):
        source_ref_ids = _known_source_ref_ids(
            assessment.source_ref_ids,
            valid_source_ref_ids,
            field_path=f"claim_assessments[{assessment_index}].source_ref_ids",
            reference_defects=reference_defects,
        )
        changed = changed or source_ref_ids != assessment.source_ref_ids
        claim_assessments.append(
            assessment.model_copy(update={"source_ref_ids": source_ref_ids})
            if source_ref_ids != assessment.source_ref_ids
            else assessment
        )

    for item_index, item in enumerate(output.missing_high_signal_items):
        source_ref_ids = _known_source_ref_ids(
            item.source_ref_ids,
            valid_source_ref_ids,
            field_path=f"missing_high_signal_items[{item_index}].source_ref_ids",
            reference_defects=reference_defects,
        )
        changed = changed or source_ref_ids != item.source_ref_ids
        missing_high_signal_items.append(
            item.model_copy(update={"source_ref_ids": source_ref_ids})
            if source_ref_ids != item.source_ref_ids
            else item
        )

    for finding_index, finding in enumerate(output.findings):
        references = []
        finding_changed = False
        for reference_index, reference in enumerate(finding.references):
            if reference.kind != "source_ref" or reference.id in valid_source_ref_ids:
                references.append(reference)
                continue
            reference_defects.append(
                _reference_defect(
                    field_path=f"findings[{finding_index}].references[{reference_index}].id",
                    reference_id=reference.id,
                )
            )
            finding_changed = True
        changed = changed or finding_changed
        findings.append(finding.model_copy(update={"references": references}) if finding_changed else finding)

    if changed:
        output = output.model_copy(
            update={
                "claim_assessments": claim_assessments,
                "missing_high_signal_items": missing_high_signal_items,
                "findings": findings,
            }
        )
    return ValidatedQualityAssessment(
        output=output,
        reference_defects=tuple(reference_defects[:_REFERENCE_DEFECTS_MAX_LENGTH]),
        omitted_reference_defect_count=max(len(reference_defects) - _REFERENCE_DEFECTS_MAX_LENGTH, 0),
    )


def _known_source_ref_ids(
    source_ref_ids: list[str],
    valid_source_ref_ids: frozenset[str],
    *,
    field_path: str,
    reference_defects: list[QualityReferenceDefect],
) -> list[str]:
    known_source_ref_ids = []
    for index, source_ref_id in enumerate(source_ref_ids):
        if source_ref_id in valid_source_ref_ids:
            known_source_ref_ids.append(source_ref_id)
            continue
        reference_defects.append(_reference_defect(field_path=f"{field_path}[{index}]", reference_id=source_ref_id))
    return known_source_ref_ids


def _reference_defect(*, field_path: str, reference_id: str) -> QualityReferenceDefect:
    return QualityReferenceDefect(
        field_path=field_path[:_REFERENCE_DEFECT_PATH_MAX_LENGTH],
        reference_id=reference_id[:_REFERENCE_DEFECT_ID_MAX_LENGTH],
    )


def _canonicalize_quality_assessment_source_refs(
    output: SemanticQualityAssessmentOutput,
    source_ref_aliases: QualitySourceRefAliases,
) -> SemanticQualityAssessmentOutput:
    claim_assessments = []
    missing_high_signal_items = []
    findings = []
    changed = False
    for assessment in output.claim_assessments:
        source_ref_ids = [
            source_ref_aliases.canonical_source_ref_id(source_ref_id) for source_ref_id in assessment.source_ref_ids
        ]
        rationale = _canonicalize_alias_text(
            assessment.rationale,
            source_ref_aliases,
            max_length=QUALITY_BOUNDED_TEXT_MAX_LENGTH,
        )
        changed = changed or source_ref_ids != assessment.source_ref_ids or rationale != assessment.rationale
        claim_assessments.append(
            assessment.model_copy(update={"source_ref_ids": source_ref_ids, "rationale": rationale})
        )
    for item in output.missing_high_signal_items:
        source_ref_ids = [
            source_ref_aliases.canonical_source_ref_id(source_ref_id) for source_ref_id in item.source_ref_ids
        ]
        description = _canonicalize_alias_text(
            item.description,
            source_ref_aliases,
            max_length=QUALITY_BOUNDED_TEXT_MAX_LENGTH,
        )
        changed = changed or source_ref_ids != item.source_ref_ids or description != item.description
        missing_high_signal_items.append(
            item.model_copy(update={"source_ref_ids": source_ref_ids, "description": description})
        )
    for finding in output.findings:
        references = []
        finding_changed = False
        for reference in finding.references:
            if reference.kind != "source_ref":
                references.append(reference)
                continue
            reference_id = source_ref_aliases.canonical_source_ref_id(reference.id)
            finding_changed = finding_changed or reference_id != reference.id
            references.append(reference.model_copy(update={"id": reference_id}))
        message = _canonicalize_alias_text(
            finding.message,
            source_ref_aliases,
            max_length=QUALITY_BOUNDED_TEXT_MAX_LENGTH,
        )
        details = _canonicalize_alias_metadata(finding.details, source_ref_aliases)
        finding_changed = finding_changed or message != finding.message or details != finding.details
        changed = changed or finding_changed
        findings.append(
            finding.model_copy(update={"references": references, "message": message, "details": details})
            if finding_changed
            else finding
        )
    overall_rationale = _canonicalize_alias_text(
        output.overall_rationale,
        source_ref_aliases,
        max_length=QUALITY_BOUNDED_TEXT_MAX_LENGTH,
    )
    changed = changed or overall_rationale != output.overall_rationale
    if not changed:
        return output
    return output.model_copy(
        update={
            "claim_assessments": claim_assessments,
            "missing_high_signal_items": missing_high_signal_items,
            "findings": findings,
            "overall_rationale": overall_rationale,
        }
    )


def _canonicalize_alias_text(
    value: str | None,
    source_ref_aliases: QualitySourceRefAliases,
    *,
    max_length: int,
) -> str | None:
    if value is None:
        return None
    result = _SOURCE_REF_ALIAS_PATTERN.sub(
        lambda match: source_ref_aliases.source_ref_id_by_alias.get(match.group(0), "unknown source ref"),
        value,
    )
    if len(result) <= max_length:
        return result
    compact = _SOURCE_REF_ALIAS_PATTERN.sub("cited source", value)
    if len(compact) <= max_length:
        return compact
    return compact[:max_length].rstrip()


def _canonicalize_alias_metadata(
    metadata: Mapping[str, Any],
    source_ref_aliases: QualitySourceRefAliases,
) -> Mapping[str, Any]:
    return {
        key: _canonicalize_alias_text(value, source_ref_aliases, max_length=_QUALITY_METADATA_TEXT_MAX_LENGTH)
        if isinstance(value, str)
        else value
        for key, value in metadata.items()
    }


def _create_pydantic_ai_agent(model: str, output_type: type[BaseModel], agent_factory: AgentFactory | None) -> Any:
    factory = agent_factory if agent_factory is not None else _pydantic_ai_agent_factory()
    return factory(model, output_type=output_type)


async def _run_pydantic_ai_agent(agent: Any, prompt: str) -> Any:
    run = getattr(agent, "run", None)
    if run is None:
        return await asyncio.to_thread(agent.run_sync, prompt)
    result = run(prompt)
    if inspect.isawaitable(result):
        return await result
    return result


def _pydantic_ai_agent_factory() -> AgentFactory:
    if PydanticAIAgent is None:
        raise PydanticAIDependencyError()
    return cast(AgentFactory, PydanticAIAgent)


def _extract_quality_assessment_output(run_result: Any) -> SemanticQualityAssessmentOutput:
    output = getattr(run_result, "output", None)
    if isinstance(output, SemanticQualityAssessmentOutput):
        return output
    return SemanticQualityAssessmentOutput.model_validate(output)


def _render_quality_assessment_prompt(packet: QualityPacket) -> str:
    packet_json = json.dumps(
        quality_packet_prompt_data(packet),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (
        "You are assessing the semantic quality of a Pi coding-session interpretation. "
        "Use only the bounded packet data below. Do not reference raw transcript lines, "
        "provider credentials, omitted content, or outside knowledge. Return a "
        "SemanticQualityAssessmentOutput object.\n\n"
        "Assessment criteria:\n"
        "- semantic_status must be 'passed', 'degraded', or 'failed'.\n"
        "- Judge whether claims are supported by cited activity_text and source refs.\n"
        "- Citation ids in Quality packet JSON are short source-ref aliases. Copy them exactly; "
        "do not invent, shorten, or expand ids.\n"
        "- Flag overbroad, vague, duplicate, noisy, or wrongly-kind claims.\n"
        "- Flag summary intent that is invented or not supported by the packet.\n"
        "- Identify missed high-signal decisions, constraints, preferences, patterns, knowledge, or actions.\n"
        "- Findings and rationales must cite packet ids; do not quote long source text.\n"
        "- Output must satisfy these hard schema limits. Be concise rather than exhaustive.\n"
        f"- Every message, rationale, and description string must be <= {QUALITY_BOUNDED_TEXT_MAX_LENGTH} "
        "characters.\n"
        f"- findings must contain <= {QUALITY_SEMANTIC_FINDINGS_MAX_LENGTH} items.\n"
        f"- claim_assessments must contain <= {QUALITY_CLAIM_ASSESSMENTS_MAX_LENGTH} items.\n"
        f"- missing_high_signal_items must contain <= {QUALITY_MISSING_HIGH_SIGNAL_ITEMS_MAX_LENGTH} items.\n"
        "- overall_rationale may be null; if present, keep it to one short sentence.\n\n"
        f"Quality packet JSON:\n{packet_json}"
    )


def _quality_report_from_semantic_output(
    *,
    packet: QualityPacket,
    validated: ValidatedQualityAssessment,
    model_metadata: Mapping[str, Any],
    prompt_version: str,
) -> QualityReportDraft:
    semantic_status = _semantic_status_with_quality_limits(validated, packet)
    quality_status, quality_reason = _semantic_quality_status(semantic_status)
    output = validated.output
    semantic_findings = list(output.findings)
    if validated.reference_defect_count:
        semantic_findings.append(_unresolved_reference_finding(packet, validated))
    deterministic_report = packet.deterministic_report
    return QualityReportDraft(
        quality_status=quality_status,
        quality_reason=quality_reason,
        derivation_status=deterministic_report.derivation_status,
        deterministic_status=deterministic_report.deterministic_status,
        semantic_status=semantic_status,
        promotable=compute_promotable(
            snapshot_status=packet.readiness.snapshot_status,
            derivation_status=deterministic_report.derivation_status,
            deterministic_status=deterministic_report.deterministic_status,
            semantic_status=semantic_status,
            quality_status=quality_status,
        ),
        deterministic_findings=list(deterministic_report.deterministic_findings),
        semantic_findings=semantic_findings,
        claim_assessments=list(output.claim_assessments),
        missing_high_signal_items=list(output.missing_high_signal_items),
        model_metadata=dict(model_metadata),
        assessment_metadata={
            **deterministic_report.assessment_metadata,
            "semantic_finding_count": len(semantic_findings),
            "claim_assessment_count": len(output.claim_assessments),
            "missing_high_signal_item_count": len(output.missing_high_signal_items),
            "quality_reference_defect_count": validated.reference_defect_count,
        },
        prompt_version=prompt_version,
    )


def _semantic_status_with_quality_limits(validated: ValidatedQualityAssessment, packet: QualityPacket) -> str:
    semantic_status = _semantic_status_with_reference_defects(validated)
    if semantic_status == SEMANTIC_STATUS_PASSED and _has_partial_episode_coverage(packet):
        return SEMANTIC_STATUS_DEGRADED
    return semantic_status


def _semantic_status_with_reference_defects(validated: ValidatedQualityAssessment) -> str:
    if validated.reference_defect_count and validated.output.semantic_status == SEMANTIC_STATUS_PASSED:
        return SEMANTIC_STATUS_DEGRADED
    return validated.output.semantic_status


def _has_partial_episode_coverage(packet: QualityPacket) -> bool:
    coverage = packet.snapshot_metadata.get("episode_interpretation")
    return isinstance(coverage, Mapping) and coverage.get("coverage_status") == "partial"


def _unresolved_reference_finding(
    packet: QualityPacket,
    validated: ValidatedQualityAssessment,
) -> QualityFinding:
    return QualityFinding(
        code=FINDING_CODE_QUALITY_ASSESSMENT_REFERENCE_UNRESOLVED,
        severity="warning",
        message=_UNRESOLVED_REFERENCE_FINDING_MESSAGE,
        references=[QualityFindingReference(kind="snapshot", id=str(packet.snapshot_id))],
        details={
            "unresolved_reference_count": validated.reference_defect_count,
            "unresolved_reference_locations": _reference_defect_locations(validated.reference_defects),
        },
    )


def _reference_defect_locations(reference_defects: tuple[QualityReferenceDefect, ...]) -> str:
    locations = []
    for defect in reference_defects:
        location = _reference_defect_location(defect.field_path)
        if location not in locations:
            locations.append(location)
    return "; ".join(locations)[:_QUALITY_METADATA_TEXT_MAX_LENGTH]


def _reference_defect_location(field_path: str) -> str:
    if field_path.startswith("claim_assessments"):
        return "claim_assessments.source_ref_ids"
    if field_path.startswith("missing_high_signal_items"):
        return "missing_high_signal_items.source_ref_ids"
    if field_path.startswith("findings"):
        return "findings.references"
    return "quality_assessment.references"


def _semantic_quality_status(semantic_status: str) -> tuple[str, str | None]:
    if semantic_status == SEMANTIC_STATUS_PASSED:
        return QUALITY_STATUS_HEALTHY, None
    if semantic_status == SEMANTIC_STATUS_DEGRADED:
        return QUALITY_STATUS_DEGRADED, QUALITY_STATUS_REASON_SEMANTIC_DEGRADED
    if semantic_status == SEMANTIC_STATUS_FAILED:
        return QUALITY_STATUS_FAILED, QUALITY_STATUS_REASON_SEMANTIC_FAILED
    return QUALITY_STATUS_FAILED, QUALITY_STATUS_REASON_SEMANTIC_FAILED


def _validate_packet_ready_for_assessment(packet: QualityPacket) -> None:
    if not packet.readiness.can_assess_semantically:
        reason = packet.readiness.quality_reason or packet.readiness.blocked_reason
        raise QualityAssessmentUnavailableError.packet_not_ready(reason)


def _pydantic_ai_model_metadata(model: str) -> Mapping[str, Any]:
    return {
        "provider": _provider_from_model(model),
        "model": model,
        "mode": PYDANTIC_AI_QUALITY_ASSESSOR_MODE,
        "schema_version": QUALITY_ASSESSMENT_SCHEMA_VERSION,
    }


def _deterministic_model_metadata() -> Mapping[str, Any]:
    return {
        "provider": "pi-memory",
        "model": DETERMINISTIC_QUALITY_ASSESSOR_MODEL,
        "mode": DETERMINISTIC_QUALITY_ASSESSOR_MODE,
        "schema_version": QUALITY_ASSESSMENT_SCHEMA_VERSION,
    }


def _provider_from_model(model: str) -> str | None:
    provider, separator, _model_name = model.partition(":")
    return provider if separator else None
