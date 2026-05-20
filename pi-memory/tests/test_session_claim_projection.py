from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pi_memory.db import (
    Database,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.db.schema import (
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_DELETED,
    MEMORY_PROJECTION_STATUS_FAILED,
    MEMORY_PROJECTION_STATUS_INDEXED,
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
)
from pi_memory.projection import ProjectionDocument, ProjectionHit, ProjectionMetadataValue, project_session_claims
from sqlalchemy import select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path: Path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


class ProjectionUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("projection backend unavailable with secret-free detail")


class FakeProjection:
    def __init__(
        self,
        *,
        should_fail: bool = False,
        collection_name: str = MEMORY_PROJECTION_COLLECTION_NAME,
    ) -> None:
        self.should_fail = should_fail
        self._collection_name = collection_name
        self.upserts: list[list[ProjectionDocument]] = []

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def embedding_model(self) -> str:
        return "fake-embedding-model"

    def upsert(self, documents: Sequence[ProjectionDocument]) -> None:
        self.upserts.append(list(documents))
        if self.should_fail:
            raise ProjectionUnavailableError

    def query(
        self,
        _text: str,
        *,
        filters: Mapping[str, ProjectionMetadataValue] | None = None,
        limit: int = 10,
    ) -> list[ProjectionHit]:
        _ = filters, limit
        return []


def create_quality_report(
    database: Database,
    *,
    claims: list[dict[str, Any]] | None = None,
    promotable: bool = True,
    snapshot_status: str = SESSION_INTERPRETATION_STATUS_COMPLETED,
) -> tuple[int, int]:
    with database.session() as session:
        memory_session = MemorySession(
            session_id="pi-session-1",
            cwd="/repo/basecamp",
            worktree_label="wt-memory",
        )
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            status=snapshot_status,
            blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
            if snapshot_status == SESSION_INTERPRETATION_STATUS_BLOCKED
            else None,
            analyzed_through_byte_offset=123,
            claim_source_activity_count=2,
            interpretation_json={
                "summary": "Session summary.",
                "claims": claims if claims is not None else sample_claims(),
            },
            citations_json=sample_citations(),
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
                {"claim_index": 0, "status": "supported", "source_ref_ids": ["source-1"]},
            ],
            prompt_version="quality-v1",
        )
        session.add(report)
        session.flush()
        return report.id, snapshot.id


def sample_claims() -> list[dict[str, Any]]:
    return [
        {
            "source_ref_ids": ["source-1"],
            "kind": "decision",
            "statement": "Use persisted quality reports for promotion eligibility.",
            "confidence": 0.91,
        },
        {
            "source_ref_ids": ["source-2"],
            "kind": "constraint",
            "statement": "Do not recompute Phase 5C quality checks during projection.",
            "confidence": 0.87,
        },
    ]


def sample_citations() -> list[dict[str, Any]]:
    return [
        {
            "usage": "claim",
            "claim_index": 0,
            "claim_kind": "decision",
            "source_ref_id": "source-1",
            "activity_unit_id": 10,
            "episode_id": 1,
            "episode_ordinal": 0,
            "activity_index": 0,
            "activity_kind": "user_text",
            "source_origin": "local",
            "claim_source_allowed": True,
            "source_entry_row_ids": [100],
            "byte_start": 0,
            "byte_end": 50,
        },
        {
            "usage": "claim",
            "claim_index": 1,
            "claim_kind": "constraint",
            "source_ref_id": "source-2",
            "activity_unit_id": 11,
            "episode_id": 1,
            "episode_ordinal": 0,
            "activity_index": 1,
            "activity_kind": "assistant_text",
            "source_origin": "local",
            "claim_source_allowed": True,
            "source_entry_row_ids": [101],
            "byte_start": 51,
            "byte_end": 100,
        },
    ]


def projection_records(database: Database) -> list[MemoryProjectionRecord]:
    with database.session() as session:
        return list(
            session.scalars(
                select(MemoryProjectionRecord).order_by(MemoryProjectionRecord.claim_index),
            ),
        )


def test_missing_report_returns_ineligible_result(database: Database) -> None:
    projection = FakeProjection()

    with database.session() as session:
        result = project_session_claims(session, report_id=9999, projection=projection)

    assert result.report_id == 9999
    assert result.snapshot_id is None
    assert result.eligible is False
    assert result.reason == "report_not_found"
    assert result.indexed_count == 0
    assert result.skipped_count == 0
    assert result.deleted_count == 0
    assert result.failed_count == 0
    assert projection.upserts == []


def test_blocked_snapshot_is_ineligible_noop(database: Database) -> None:
    report_id, snapshot_id = create_quality_report(database, snapshot_status=SESSION_INTERPRETATION_STATUS_BLOCKED)
    projection = FakeProjection()

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)

    assert result.snapshot_id == snapshot_id
    assert result.eligible is False
    assert result.reason == "snapshot_not_completed"
    assert result.skipped_count == 2
    assert projection.upserts == []
    assert projection_records(database) == []


def test_eligible_report_with_no_claims_returns_empty_success(database: Database) -> None:
    report_id, snapshot_id = create_quality_report(database, claims=[])
    projection = FakeProjection()

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)

    assert result.snapshot_id == snapshot_id
    assert result.eligible is True
    assert result.indexed_count == 0
    assert result.skipped_count == 0
    assert result.deleted_count == 0
    assert result.failed_count == 0
    assert projection.upserts == []
    assert projection_records(database) == []


def test_eligible_report_creates_records_and_projection_documents(database: Database) -> None:
    report_id, snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)

    records = projection_records(database)
    documents = projection.upserts[0]

    assert result.report_id == report_id
    assert result.snapshot_id == snapshot_id
    assert result.eligible is True
    assert result.indexed_count == 2
    assert result.skipped_count == 0
    assert result.deleted_count == 0
    assert result.failed_count == 0
    assert len(records) == 2
    assert len(documents) == 2
    assert {document.chroma_id for document in documents} == {
        f"session_claim:{snapshot_id}:0",
        f"session_claim:{snapshot_id}:1",
    }
    assert "Use persisted quality reports" in documents[0].text
    assert "raw transcript" not in documents[0].text.lower()


def test_records_and_documents_have_required_invariants_and_metadata(database: Database) -> None:
    report_id, snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)

    record = projection_records(database)[0]
    document = projection.upserts[0][0]

    assert record.record_type == MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM
    assert record.memory_layer == MEMORY_LAYER_SHORT_TERM
    assert record.source_table == "session_interpretation_snapshots"
    assert record.source_id == snapshot_id
    assert record.snapshot_id == snapshot_id
    assert record.quality_report_id == report_id
    assert record.claim_index == 0
    assert record.collection_name == MEMORY_PROJECTION_COLLECTION_NAME
    assert record.record_key == f"session_claim:{snapshot_id}:0"
    assert record.chroma_id == f"session_claim:{snapshot_id}:0"
    assert record.status == MEMORY_PROJECTION_STATUS_INDEXED
    assert record.embedding_model == "fake-embedding-model"
    assert record.recall_visible is True
    assert record.relation_visible is True
    assert len(record.content_hash) == 64
    assert record.metadata_json["session_id"] == "pi-session-1"
    assert record.metadata_json["session_cwd"] == "/repo/basecamp"
    assert "repo_name" not in record.metadata_json
    assert record.metadata_json["worktree_label"] == "wt-memory"
    assert record.metadata_json["transcript_id"] is not None
    assert record.metadata_json["quality_status"] == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
    assert record.metadata_json["semantic_status"] == SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
    assert record.metadata_json["deterministic_status"] == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
    assert record.metadata_json["derivation_status"] == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
    assert record.metadata_json["promotable"] is True
    assert record.metadata_json["source_refs"][0]["source_ref_id"] == "source-1"
    assert record.metadata_json["source_refs"][0]["activity_unit_id"] == 10

    assert document.metadata["record_type"] == MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM
    assert document.metadata["memory_layer"] == MEMORY_LAYER_SHORT_TERM
    assert document.metadata["quality_status"] == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
    assert document.metadata["session_id"] == "pi-session-1"
    assert document.metadata["session_cwd"] == "/repo/basecamp"
    assert "repo_name" not in document.metadata
    assert document.metadata["worktree_label"] == "wt-memory"
    assert document.metadata["claim_kind"] == "decision"
    assert document.metadata["claim_confidence"] == 0.91
    assert document.metadata["source_ref_count"] == 1
    assert document.metadata["projection_status"] == MEMORY_PROJECTION_STATUS_INDEXED
    assert document.metadata["embedding_model"] == "fake-embedding-model"
    assert all(isinstance(value, str | int | float | bool) for value in document.metadata.values())


def test_rerunning_same_report_is_idempotent(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)
    first_records = projection_records(database)
    first_hashes = [record.content_hash for record in first_records]
    first_ids = [record.id for record in first_records]

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)
    second_records = projection_records(database)

    assert result.indexed_count == 2
    assert len(second_records) == 2
    assert [record.id for record in second_records] == first_ids
    assert [record.content_hash for record in second_records] == first_hashes
    assert len(projection.upserts) == 2


def test_custom_collection_name_is_persisted_and_idempotent(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection(collection_name="custom-session-claims")

    with database.session() as session:
        first_result = project_session_claims(session, report_id, projection)
    first_records = projection_records(database)
    first_ids = [record.id for record in first_records]

    with database.session() as session:
        second_result = project_session_claims(session, report_id, projection)
    second_records = projection_records(database)

    assert first_result.indexed_count == 2
    assert second_result.indexed_count == 2
    assert len(second_records) == 2
    assert [record.id for record in second_records] == first_ids
    assert {record.collection_name for record in second_records} == {"custom-session-claims"}
    assert len(projection.upserts) == 2


def test_claim_content_change_updates_existing_row_without_duplicate(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)
    original_records = projection_records(database)
    original_hash = original_records[0].content_hash
    original_id = original_records[0].id

    with database.session() as session:
        report = session.get(SessionInterpretationQualityReport, report_id)
        assert report is not None
        claims = list(report.snapshot.interpretation_json["claims"])
        claims[0] = {**claims[0], "statement": "Updated projection statement."}
        report.snapshot.interpretation_json = {**report.snapshot.interpretation_json, "claims": claims}
        project_session_claims(session, report_id, projection)

    updated_records = projection_records(database)

    assert len(updated_records) == 2
    assert updated_records[0].id == original_id
    assert updated_records[0].content_hash != original_hash
    assert updated_records[0].metadata_json["claim_statement"] == "Updated projection statement."


def test_fewer_claims_marks_missing_old_claim_deleted(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)

    with database.session() as session:
        report = session.get(SessionInterpretationQualityReport, report_id)
        assert report is not None
        report.snapshot.interpretation_json = {
            **report.snapshot.interpretation_json,
            "claims": [report.snapshot.interpretation_json["claims"][0]],
        }
        result = project_session_claims(session, report_id, projection)

    records = projection_records(database)

    assert result.indexed_count == 1
    assert result.deleted_count == 1
    assert len(records) == 2
    assert records[0].status == MEMORY_PROJECTION_STATUS_INDEXED
    assert records[1].status == MEMORY_PROJECTION_STATUS_DELETED
    assert records[1].recall_visible is False
    assert records[1].relation_visible is False
    assert len(projection.upserts[-1]) == 1
    assert projection.upserts[-1][0].chroma_id.endswith(":0")


def test_non_promotable_report_is_ineligible_noop(database: Database) -> None:
    report_id, snapshot_id = create_quality_report(database, promotable=False)
    projection = FakeProjection()

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)

    assert result.report_id == report_id
    assert result.snapshot_id == snapshot_id
    assert result.eligible is False
    assert result.reason == "report_not_promotable"
    assert result.indexed_count == 0
    assert result.skipped_count == 2
    assert projection.upserts == []
    assert projection_records(database) == []


def test_non_promotable_report_hides_existing_projection_records(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)
        report = session.get(SessionInterpretationQualityReport, report_id)
        assert report is not None
        report.promotable = False
        result = project_session_claims(session, report_id, projection)

    records = projection_records(database)

    assert result.eligible is False
    assert result.reason == "report_not_promotable"
    assert result.deleted_count == 2
    assert {record.status for record in records} == {MEMORY_PROJECTION_STATUS_DELETED}
    assert all(record.recall_visible is False for record in records)
    assert all(record.relation_visible is False for record in records)


def test_repeated_non_promotable_projection_does_not_recount_deleted_records(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection()

    with database.session() as session:
        project_session_claims(session, report_id, projection)
        report = session.get(SessionInterpretationQualityReport, report_id)
        assert report is not None
        report.promotable = False
        first_result = project_session_claims(session, report_id, projection)
        second_result = project_session_claims(session, report_id, projection)

    assert first_result.deleted_count == 2
    assert second_result.deleted_count == 0


def test_projection_upsert_exception_marks_rows_failed(database: Database) -> None:
    report_id, _snapshot_id = create_quality_report(database)
    projection = FakeProjection(should_fail=True)

    with database.session() as session:
        result = project_session_claims(session, report_id, projection)

    records = projection_records(database)

    assert result.eligible is True
    assert result.indexed_count == 0
    assert result.failed_count == 2
    assert len(records) == 2
    assert {record.status for record in records} == {MEMORY_PROJECTION_STATUS_FAILED}
    assert all(record.embedding_model is None for record in records)
    assert all(record.last_error == "projection backend unavailable with secret-free detail" for record in records)
    assert len(projection.upserts) == 1
