"""Structured interpretation output contracts and pure validators."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from pi_memory.constants import (
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
)
from pi_memory.interpretation.packets import (
    EpisodePacket,
    InterpretationPacket,
    SourceRef,
    build_episode_interpretation_packet,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ClaimKind = Literal["decision", "constraint", "knowledge", "preference", "pattern", "action"]
CitationUsage = Literal["summary", "claim", "open_question", "context"]
EpisodeInterpretationStatus = Literal["completed", "skipped_no_claim_sources", "failed"]
SessionInterpretationCoverageStatus = Literal["complete", "partial", "skipped_no_claim_sources"]
SESSION_INTERPRETATION_AGGREGATION_MODE_EPISODE_CLAIM_CONCAT = "episode_claim_concat"
_ALLOWED_CLAIM_SOURCE_ORIGINS = frozenset((SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_MIXED))


class InterpretationValidationError(Exception):
    """Raised when structured interpretation output is invalid for a packet."""

    @classmethod
    def schema_error(cls) -> InterpretationValidationError:
        return cls("Interpretation output does not match the required schema")

    @classmethod
    def identity_mismatch(cls, field_name: str) -> InterpretationValidationError:
        return cls(f"Interpretation output {field_name} does not match the source packet")

    @classmethod
    def unknown_source_ref(cls, source_ref_id: str) -> InterpretationValidationError:
        return cls(f"Interpretation output cites unknown source_ref_id: {source_ref_id}")

    @classmethod
    def packet_not_interpretable(cls) -> InterpretationValidationError:
        return cls("Interpretation output cannot be applied to a non-interpretable source packet")

    @classmethod
    def unsupported_claim_sources(cls, claim_index: int) -> InterpretationValidationError:
        return cls(f"Interpretation claim at index {claim_index} lacks local or mixed claim-source support")

    @classmethod
    def empty_claims(cls) -> InterpretationValidationError:
        return cls("Interpretation output must include at least one claim when claim sources are available")


class InterpretationClaim(BaseModel):
    """Source-backed claim extracted from an interpretation model response."""

    model_config = ConfigDict(extra="forbid")

    source_ref_ids: list[NonEmptyString] = Field(min_length=1)
    kind: ClaimKind
    statement: NonEmptyString
    confidence: float = Field(ge=0.0, le=1.0)


class InterpretationOpenQuestion(BaseModel):
    """Open question surfaced by an interpretation model response."""

    model_config = ConfigDict(extra="forbid")

    question: NonEmptyString
    source_ref_ids: list[NonEmptyString] = Field(default_factory=list)


class InterpretationCitation(BaseModel):
    """General citation emitted by an interpretation model response."""

    model_config = ConfigDict(extra="forbid")

    source_ref_id: NonEmptyString
    usage: CitationUsage


class InterpretationOutput(BaseModel):
    """Structured interpretation response expected from future model calls."""

    model_config = ConfigDict(extra="forbid")

    analysis_run_id: int
    analyzed_through_entry_id: int | None
    analyzed_through_byte_offset: int = Field(ge=0)
    goal: NonEmptyString | None = None
    summary: NonEmptyString
    claims: list[InterpretationClaim] = Field(default_factory=list)
    open_questions: list[InterpretationOpenQuestion] = Field(default_factory=list)
    citations: list[InterpretationCitation] = Field(default_factory=list)


@dataclass(frozen=True)
class SourceRefAliases:
    """Prompt-safe source-ref aliases mapped to canonical source refs."""

    alias_by_source_ref_id: Mapping[str, str]
    source_ref_id_by_alias: Mapping[str, str]

    def alias_for(self, source_ref_id: str) -> str:
        """Return the prompt alias for a canonical source ref."""
        return self.alias_by_source_ref_id[source_ref_id]

    def canonical_source_ref_id(self, source_ref_id: str) -> str:
        """Return the canonical source ref for an alias or canonical id."""
        return self.source_ref_id_by_alias.get(source_ref_id, source_ref_id)


@dataclass(frozen=True)
class ValidatedInterpretation:
    """Validated interpretation payloads ready for future snapshot persistence."""

    output: InterpretationOutput
    interpretation_json: Mapping[str, Any]
    citations_json: list[Mapping[str, Any]]


class EpisodeInterpretationFailureMetadata(BaseModel):
    """Safe failure metadata for a failed episode interpretation."""

    model_config = ConfigDict(extra="forbid")

    error_type: NonEmptyString
    safe_message: NonEmptyString | None = None
    cause_type: NonEmptyString | None = None
    prompt_char_count: int | None = Field(default=None, ge=0)
    prompt_byte_count: int | None = Field(default=None, ge=0)
    model_metadata: dict[str, Any] = Field(default_factory=dict)


class EpisodeInterpretationCoverage(BaseModel):
    """Deterministic coverage metadata for an aggregated session interpretation."""

    model_config = ConfigDict(extra="forbid")

    aggregation_mode: Literal["episode_claim_concat"] = SESSION_INTERPRETATION_AGGREGATION_MODE_EPISODE_CLAIM_CONCAT
    coverage_status: SessionInterpretationCoverageStatus
    total_episode_count: int = Field(ge=0)
    claim_source_episode_count: int = Field(ge=0)
    completed_episode_count: int = Field(ge=0)
    skipped_episode_count: int = Field(ge=0)
    failed_episode_count: int = Field(ge=0)
    total_claim_source_activity_count: int = Field(ge=0)
    completed_claim_source_activity_count: int = Field(ge=0)
    skipped_claim_source_activity_count: int = Field(ge=0)
    failed_claim_source_activity_count: int = Field(ge=0)


def build_source_ref_aliases(packet: InterpretationPacket) -> SourceRefAliases:
    """Build deterministic prompt aliases for packet source refs."""
    alias_by_source_ref_id: dict[str, str] = {}
    source_ref_id_by_alias: dict[str, str] = {}
    for source_ref in _ordered_source_refs(packet):
        if source_ref.source_ref_id in alias_by_source_ref_id:
            continue
        alias = f"s{len(alias_by_source_ref_id) + 1:04d}"
        alias_by_source_ref_id[source_ref.source_ref_id] = alias
        source_ref_id_by_alias[alias] = source_ref.source_ref_id
    return SourceRefAliases(
        alias_by_source_ref_id=alias_by_source_ref_id,
        source_ref_id_by_alias=source_ref_id_by_alias,
    )


def validate_interpretation_output(
    output: InterpretationOutput | Mapping[str, Any],
    packet: InterpretationPacket,
) -> ValidatedInterpretation:
    """Validate structured interpretation output against its source packet.

    Args:
        output: Pydantic output model or mapping produced by a model adapter.
        packet: Read-only interpretation packet used as the output source.

    Returns:
        Frozen validated interpretation payload wrapper.

    Raises:
        InterpretationValidationError: If schema, packet identity, or citations are invalid.
    """
    model = _coerce_output(output)
    _validate_packet_interpretable(packet)
    _validate_packet_identity(model, packet)
    model = _canonicalize_output_source_refs(model, build_source_ref_aliases(packet))
    source_refs = _source_refs_by_id(packet)
    _validate_source_ref_ids(model, source_refs)
    _validate_claim_presence(model)
    _validate_claim_support(model, source_refs)
    return ValidatedInterpretation(
        output=model,
        interpretation_json=model.model_dump(mode="json", exclude_none=True),
        citations_json=_citations_json(model, source_refs),
    )


def validate_episode_interpretation_output(
    output: InterpretationOutput | Mapping[str, Any],
    packet: InterpretationPacket,
    episode_packet: EpisodePacket,
) -> ValidatedInterpretation:
    """Validate structured interpretation output against one episode packet."""
    return validate_interpretation_output(
        output,
        build_episode_interpretation_packet(packet, episode_packet),
    )


def _coerce_output(output: InterpretationOutput | Mapping[str, Any]) -> InterpretationOutput:
    if isinstance(output, InterpretationOutput):
        return output
    try:
        return InterpretationOutput.model_validate(output)
    except ValidationError as error:
        raise InterpretationValidationError.schema_error() from error


def _canonicalize_output_source_refs(
    output: InterpretationOutput,
    source_ref_aliases: SourceRefAliases,
) -> InterpretationOutput:
    claims = []
    open_questions = []
    citations = []
    changed = False
    for claim in output.claims:
        source_ref_ids = [
            source_ref_aliases.canonical_source_ref_id(source_ref_id) for source_ref_id in claim.source_ref_ids
        ]
        changed = changed or source_ref_ids != claim.source_ref_ids
        claims.append(claim.model_copy(update={"source_ref_ids": source_ref_ids}))
    for question in output.open_questions:
        source_ref_ids = [
            source_ref_aliases.canonical_source_ref_id(source_ref_id) for source_ref_id in question.source_ref_ids
        ]
        changed = changed or source_ref_ids != question.source_ref_ids
        open_questions.append(question.model_copy(update={"source_ref_ids": source_ref_ids}))
    for citation in output.citations:
        source_ref_id = source_ref_aliases.canonical_source_ref_id(citation.source_ref_id)
        changed = changed or source_ref_id != citation.source_ref_id
        citations.append(citation.model_copy(update={"source_ref_id": source_ref_id}))
    if not changed:
        return output
    return output.model_copy(update={"claims": claims, "open_questions": open_questions, "citations": citations})


def _validate_packet_interpretable(packet: InterpretationPacket) -> None:
    if not packet.readiness.can_call_model:
        raise InterpretationValidationError.packet_not_interpretable()


def _validate_packet_identity(output: InterpretationOutput, packet: InterpretationPacket) -> None:
    readiness = packet.readiness
    if output.analysis_run_id != readiness.latest_analysis_run_id:
        raise InterpretationValidationError.identity_mismatch("analysis_run_id")
    if output.analyzed_through_entry_id != readiness.analyzed_through_entry_id:
        raise InterpretationValidationError.identity_mismatch("analyzed_through_entry_id")
    if output.analyzed_through_byte_offset != readiness.analyzed_through_byte_offset:
        raise InterpretationValidationError.identity_mismatch("analyzed_through_byte_offset")


def _source_refs_by_id(packet: InterpretationPacket) -> dict[str, SourceRef]:
    return {source_ref.source_ref_id: source_ref for source_ref in _ordered_source_refs(packet)}


def _ordered_source_refs(packet: InterpretationPacket) -> tuple[SourceRef, ...]:
    return tuple(source_ref for episode_packet in packet.episode_packets for source_ref in episode_packet.source_refs)


def _validate_source_ref_ids(output: InterpretationOutput, source_refs: Mapping[str, SourceRef]) -> None:
    for source_ref_id in _cited_source_ref_ids(output):
        if source_ref_id not in source_refs:
            raise InterpretationValidationError.unknown_source_ref(source_ref_id)


def _cited_source_ref_ids(output: InterpretationOutput) -> tuple[str, ...]:
    source_ref_ids: list[str] = []
    for claim in output.claims:
        source_ref_ids.extend(claim.source_ref_ids)
    for question in output.open_questions:
        source_ref_ids.extend(question.source_ref_ids)
    source_ref_ids.extend(citation.source_ref_id for citation in output.citations)
    return tuple(source_ref_ids)


def _validate_claim_presence(output: InterpretationOutput) -> None:
    if not output.claims:
        raise InterpretationValidationError.empty_claims()


def _validate_claim_support(output: InterpretationOutput, source_refs: Mapping[str, SourceRef]) -> None:
    for index, claim in enumerate(output.claims):
        if not any(is_claim_source_eligible(source_refs[source_ref_id]) for source_ref_id in claim.source_ref_ids):
            raise InterpretationValidationError.unsupported_claim_sources(index)


def is_claim_source_eligible(source_ref: SourceRef) -> bool:
    """Whether a source ref may support interpretation claims."""
    return source_ref.claim_source_allowed and source_ref.source_origin in _ALLOWED_CLAIM_SOURCE_ORIGINS


def _citations_json(
    output: InterpretationOutput,
    source_refs: Mapping[str, SourceRef],
) -> list[Mapping[str, Any]]:
    citations: list[Mapping[str, Any]] = []
    for claim_index, claim in enumerate(output.claims):
        citations.extend(
            _enriched_citation(
                source_refs[source_ref_id],
                usage="claim",
                claim_index=claim_index,
                claim_kind=claim.kind,
            )
            for source_ref_id in claim.source_ref_ids
        )
    for question_index, question in enumerate(output.open_questions):
        citations.extend(
            _enriched_citation(
                source_refs[source_ref_id],
                usage="open_question",
                open_question_index=question_index,
            )
            for source_ref_id in question.source_ref_ids
        )
    citations.extend(
        _enriched_citation(source_refs[citation.source_ref_id], usage=citation.usage) for citation in output.citations
    )
    return citations


def _enriched_citation(source_ref: SourceRef, **metadata: Any) -> Mapping[str, Any]:
    return {
        **metadata,
        "source_ref_id": source_ref.source_ref_id,
        "activity_unit_id": source_ref.activity_unit_id,
        "episode_id": source_ref.episode_id,
        "episode_ordinal": source_ref.episode_ordinal,
        "activity_index": source_ref.activity_index,
        "activity_kind": source_ref.activity_kind,
        "source_origin": source_ref.source_origin,
        "claim_source_allowed": source_ref.claim_source_allowed,
        "source_entry_row_ids": list(source_ref.source_entry_row_ids),
        "byte_start": source_ref.byte_start,
        "byte_end": source_ref.byte_end,
    }
