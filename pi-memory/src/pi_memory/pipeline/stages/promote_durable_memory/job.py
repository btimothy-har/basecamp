"""Durable memory promotion pipeline stage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from pi_memory.db.constants import (
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_PROMOTED,
    DURABLE_MEMORY_STATUS_QUARANTINED,
    DURABLE_MEMORY_STATUS_REJECTED,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
)
from pi_memory.db.models import (
    Job,
    SessionInterpretationQualityReport,
)
from pi_memory.durable import (
    DurableMemoryPacketError,
    ReducerContext,
    assess_durable_memory_relations,
    build_durable_memory_evidence_packet,
    persist_reducer_decision,
    project_durable_memory_record,
)
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.pipeline.runtime.adapters import PipelineAdapters
from pi_memory.pipeline.stages.promote_durable_memory.persistence import (
    add_durable_memory_audit_event,
    add_relation_assessed_audit_event,
    project_archived_related_memory,
    replace_durable_memory_sources,
    upsert_durable_memory_candidate,
)
from pi_memory.pipeline.utils import payloads


class PromoteDurableMemoryJob:
    """Promote quality-assessed claims into durable memory."""

    kind = JOB_KIND_PROMOTE_DURABLE_MEMORY

    def __init__(self, adapters: PipelineAdapters) -> None:
        self._adapters = adapters

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        quality_report_id = payloads.quality_report_id(job.payload_json)
        context.database.initialize()
        counts = {
            DURABLE_MEMORY_STATUS_PROMOTED: 0,
            DURABLE_MEMORY_STATUS_REJECTED: 0,
            DURABLE_MEMORY_STATUS_QUARANTINED: 0,
            DURABLE_MEMORY_STATUS_ARCHIVED: 0,
        }
        skipped_packet_count = 0
        failed_packet_count = 0
        processed_count = 0
        with context.database.session() as session:
            report = session.get(SessionInterpretationQualityReport, quality_report_id)
            if report is None:
                return {
                    "status": "completed",
                    "quality_report_id": quality_report_id,
                    "claim_count": 0,
                    "processed_count": 0,
                    "skipped_packet_count": 0,
                    "failed_packet_count": 1,
                    "final_status_counts": counts,
                    "reason": "report_not_found",
                }
            claim_count = _quality_report_claim_count(report)
            for claim_index in range(claim_count):
                try:
                    outcome = self._promote_quality_report_claim(session, job, quality_report_id, claim_index)
                except DurableMemoryPacketError:
                    failed_packet_count += 1
                    continue
                if outcome == "skipped":
                    skipped_packet_count += 1
                    continue
                processed_count += 1
                counts[outcome] = counts.get(outcome, 0) + 1

        return {
            "status": "completed",
            "quality_report_id": quality_report_id,
            "claim_count": claim_count,
            "processed_count": processed_count,
            "skipped_packet_count": skipped_packet_count,
            "failed_packet_count": failed_packet_count,
            "final_status_counts": counts,
        }

    def _promote_quality_report_claim(
        self,
        session: Session,
        job: Job,
        quality_report_id: int,
        claim_index: int,
    ) -> str:
        packet = build_durable_memory_evidence_packet(session, quality_report_id, claim_index)
        memory, upsert_outcome = upsert_durable_memory_candidate(session, packet, job.id)
        if upsert_outcome == "skipped":
            return "skipped"
        replace_durable_memory_sources(session, memory, packet)
        if upsert_outcome == "created":
            add_durable_memory_audit_event(
                session,
                memory,
                event_type="candidate_created",
                from_status=None,
                to_status=memory.status,
                reason_code="candidate_created",
                details={"quality_report_id": quality_report_id, "claim_index": claim_index},
            )
        add_durable_memory_audit_event(
            session,
            memory,
            event_type="eligibility_evaluated",
            from_status=memory.status,
            to_status=memory.status,
            reason_code="eligible" if packet.eligibility.is_eligible else f"blocked_{packet.eligibility.block_reason}",
            details={"is_eligible": packet.eligibility.is_eligible, "block_reason": packet.eligibility.block_reason},
        )
        if not packet.eligibility.is_eligible:
            decision = self._adapters.durable_reducer.decide(ReducerContext(memory, packet.eligibility, None, None))
            persist_reducer_decision(session, memory, decision)
            project_durable_memory_record(session, memory, self._adapters.memory_projection())
            return memory.status

        evaluation_result = self._adapters.candidate_evaluator().evaluate(packet)
        preliminary_decision = self._adapters.durable_reducer.decide(
            ReducerContext(memory, packet.eligibility, evaluation_result.output, None),
        )
        if preliminary_decision.reason_code != "metrics_all_healthy":
            persist_reducer_decision(session, memory, preliminary_decision, evaluation_result=evaluation_result)
            project_durable_memory_record(session, memory, self._adapters.memory_projection())
            return memory.status

        relation_result = assess_durable_memory_relations(session, memory.id, self._adapters.memory_projection())
        add_relation_assessed_audit_event(session, memory, relation_result)
        final_decision = self._adapters.durable_reducer.decide(
            ReducerContext(memory, packet.eligibility, evaluation_result.output, relation_result),
        )
        persist_reducer_decision(
            session,
            memory,
            final_decision,
            evaluation_result=evaluation_result,
            relation_result=relation_result,
        )
        project_durable_memory_record(session, memory, self._adapters.memory_projection())
        project_archived_related_memory(session, memory, relation_result, self._adapters.memory_projection())
        return memory.status


def _quality_report_claim_count(report: SessionInterpretationQualityReport) -> int:
    claims = report.snapshot.interpretation_json.get("claims")
    if not isinstance(claims, list):
        return 0
    return sum(1 for claim in claims if isinstance(claim, Mapping))
