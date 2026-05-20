from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pi_memory.db import (
    DURABLE_MEMORY_RELATION_TYPE_CONFLICTS,
    DURABLE_MEMORY_RELATION_TYPE_DUPLICATE,
    DURABLE_MEMORY_RELATION_TYPE_NOVEL,
    DURABLE_MEMORY_RELATION_TYPE_REFINES,
    DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
    DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    Database,
    DurableMemoryItem,
    DurableMemoryRelation,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.db.schema import (
    MEMORY_LAYER_LONG_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
    MEMORY_PROJECTION_STATUS_FAILED,
    MEMORY_PROJECTION_STATUS_INDEXED,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
)
from pi_memory.durable import (
    DurableMemoryNotFoundError,
    DurableMemoryProjectionError,
    assess_durable_memory_relations,
    project_durable_memory_record,
)
from pi_memory.projection import ProjectionDocument, ProjectionHit, ProjectionMetadataValue
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
        super().__init__("projection backend unavailable with private details" * 20)


class FakeDurableProjection:
    def __init__(self, *, should_fail: bool = False) -> None:
        self.should_fail = should_fail
        self.upserts: list[list[ProjectionDocument]] = []
        self.documents: dict[str, ProjectionDocument] = {}
        self.distances: dict[str, float] = {}
        self.injected_hits: list[ProjectionHit] = []
        self.queries: list[dict[str, Any]] = []

    @property
    def collection_name(self) -> str:
        return MEMORY_PROJECTION_COLLECTION_NAME

    @property
    def embedding_model(self) -> str:
        return "fake-durable-embedding-model"

    def upsert(self, documents: Sequence[ProjectionDocument]) -> None:
        batch = list(documents)
        self.upserts.append(batch)
        if self.should_fail:
            raise ProjectionUnavailableError
        for document in batch:
            self.documents[document.chroma_id] = document

    def query(
        self,
        text: str,
        *,
        filters: Mapping[str, ProjectionMetadataValue] | None = None,
        limit: int = 10,
    ) -> list[ProjectionHit]:
        self.queries.append({"text": text, "filters": filters, "limit": limit})
        hits = list(self.injected_hits)
        hits.extend(
            ProjectionHit(
                chroma_id=document.chroma_id,
                text=document.text,
                metadata=document.metadata,
                distance=self.distances.get(document.chroma_id, 0.2),
            )
            for document in self.documents.values()
            if _matches_filters(document.metadata, filters)
        )
        return sorted(hits, key=lambda hit: (hit.distance, hit.chroma_id))[:limit]


def _matches_filters(
    metadata: Mapping[str, ProjectionMetadataValue],
    filters: Mapping[str, ProjectionMetadataValue] | None,
) -> bool:
    if not filters:
        return True
    return all(metadata.get(key) == value for key, value in filters.items())


def create_memory_fixture(database: Database, memories: list[dict[str, Any]]) -> list[int]:
    with database.session() as session:
        memory_session = MemorySession(
            session_id="pi-session-1",
            repo_name="basecamp",
            worktree_label="wt-memory",
        )
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
            analyzed_through_byte_offset=123,
            claim_source_activity_count=2,
            interpretation_json={"summary": "Session summary.", "claims": []},
            citations_json=[],
            prompt_version="interpretation-v1",
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
            semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
            promotable=True,
            claim_assessments_json=[],
            prompt_version="quality-v1",
        )
        session.add(report)
        session.flush()

        ids: list[int] = []
        for index, spec in enumerate(memories):
            memory = DurableMemoryItem(
                session=memory_session,
                transcript=transcript,
                snapshot=snapshot,
                quality_report=report,
                status=spec.get("status", DURABLE_MEMORY_STATUS_CANDIDATE),
                claim_index=index,
                claim_kind=spec.get("claim_kind", "decision"),
                statement=spec["statement"],
                confidence=0.9,
                content_hash=f"content-hash-{index}",
                evaluation_json=spec.get("evaluation_json", {}),
                metadata_json={},
            )
            session.add(memory)
            session.flush()
            ids.append(memory.id)
        return ids


def records(database: Database) -> list[MemoryProjectionRecord]:
    with database.session() as session:
        return list(session.scalars(select(MemoryProjectionRecord).order_by(MemoryProjectionRecord.source_id)))


def relations(database: Database) -> list[DurableMemoryRelation]:
    with database.session() as session:
        return list(session.scalars(select(DurableMemoryRelation).order_by(DurableMemoryRelation.id)))


def test_projection_creates_long_term_durable_records_and_chroma_docs(database: Database) -> None:
    candidate_id, promoted_id = create_memory_fixture(
        database,
        [
            {
                "status": DURABLE_MEMORY_STATUS_CANDIDATE,
                "statement": "Use the raw candidate statement.",
                "evaluation_json": {"output": {"normalized_statement": "Use the normalized candidate statement."}},
            },
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use promoted memory."},
        ],
    )
    projection = FakeDurableProjection()

    with database.session() as session:
        candidate = session.get(DurableMemoryItem, candidate_id)
        promoted = session.get(DurableMemoryItem, promoted_id)
        assert candidate is not None
        assert promoted is not None
        project_durable_memory_record(session, candidate, projection)
        project_durable_memory_record(session, promoted, projection)

    stored_records = records(database)
    candidate_record = next(record for record in stored_records if record.source_id == candidate_id)
    promoted_record = next(record for record in stored_records if record.source_id == promoted_id)
    candidate_doc = projection.documents[f"durable_memory:{candidate_id}"]
    promoted_doc = projection.documents[f"durable_memory:{promoted_id}"]

    assert candidate_record.record_type == MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY
    assert candidate_record.memory_layer == MEMORY_LAYER_LONG_TERM
    assert candidate_record.source_table == "durable_memory_items"
    assert candidate_record.source_id == candidate_id
    assert candidate_record.durable_memory_id == candidate_id
    assert candidate_record.claim_index is None
    assert candidate_record.record_key == f"durable_memory:{candidate_id}"
    assert candidate_record.chroma_id == f"durable_memory:{candidate_id}"
    assert candidate_record.status == MEMORY_PROJECTION_STATUS_INDEXED
    assert candidate_record.embedding_model == "fake-durable-embedding-model"
    assert candidate_record.recall_visible is False
    assert candidate_record.relation_visible is True
    assert candidate_record.metadata_json["normalized_statement"] == "Use the normalized candidate statement."
    assert candidate_record.metadata_json["session_id"] == "pi-session-1"
    assert candidate_record.metadata_json["repo_name"] == "basecamp"
    assert candidate_record.metadata_json["transcript_id"] is not None
    assert candidate_record.metadata_json["snapshot_id"] is not None
    assert candidate_record.metadata_json["quality_report_id"] is not None
    assert len(candidate_record.content_hash) == 64

    assert promoted_record.recall_visible is True
    assert promoted_record.relation_visible is True
    assert candidate_doc.text == "Use the normalized candidate statement."
    assert candidate_doc.metadata["record_type"] == MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY
    assert candidate_doc.metadata["memory_layer"] == MEMORY_LAYER_LONG_TERM
    assert candidate_doc.metadata["durable_memory_id"] == candidate_id
    assert candidate_doc.metadata["status"] == DURABLE_MEMORY_STATUS_CANDIDATE
    assert candidate_doc.metadata["projection_status"] == MEMORY_PROJECTION_STATUS_INDEXED
    assert candidate_doc.metadata["relation_visible"] is True
    assert candidate_doc.metadata["recall_visible"] is False
    assert candidate_doc.metadata["session_id"] == "pi-session-1"
    assert promoted_doc.metadata["recall_visible"] is True


def test_assess_with_no_existing_promoted_records_returns_novel(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Use durable relation assessment."}])
    projection = FakeDurableProjection()

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    assert result.memory_id == candidate_id
    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_NOVEL
    assert result.assessment.related_memory_id is None
    assert result.resolved_hit_count == 0
    assert relations(database) == []
    with database.session() as session:
        memory = session.get(DurableMemoryItem, candidate_id)
        assert memory is not None
        assert memory.relation_summary_json["assessment"]["relation_type"] == DURABLE_MEMORY_RELATION_TYPE_NOVEL


def test_duplicate_relation_persists_after_hit_resolves_through_sqlite(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use SQLite before relation classification."},
            {"statement": "Use SQLite before relation classification."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.05
    projection.distances[f"durable_memory:{candidate_id}"] = 0.0

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    stored_relations = relations(database)
    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_DUPLICATE
    assert result.related_memory_id == promoted_id
    assert result.resolved_hit_count == 1
    assert len(stored_relations) == 1
    assert stored_relations[0].memory_id == candidate_id
    assert stored_relations[0].related_memory_id == promoted_id
    assert stored_relations[0].relation_type == DURABLE_MEMORY_RELATION_TYPE_DUPLICATE
    assert stored_relations[0].confidence == 1.0
    assert stored_relations[0].metadata_json["chroma_id"] == f"durable_memory:{promoted_id}"
    assert stored_relations[0].metadata_json["classifier_mode"] == "deterministic-chroma-v1"


def test_refines_relation_persists_when_candidate_contains_promoted_statement(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use SQLite"},
            {"statement": "Use SQLite for canonical durable memory state."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.2

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_REFINES
    assert result.assessment.related_memory_id == promoted_id
    assert relations(database)[0].relation_type == DURABLE_MEMORY_RELATION_TYPE_REFINES


def test_reinforces_relation_persists_for_close_non_duplicate_hit(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Keep SQLite as canonical memory storage."},
            {"statement": "Prefer SQLite-backed projection metadata."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.2

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_REINFORCES
    assert result.assessment.related_memory_id == promoted_id
    assert result.assessment.similarity_score == 0.8
    assert relations(database)[0].relation_type == DURABLE_MEMORY_RELATION_TYPE_REINFORCES


def test_conflict_relation_persists_for_positive_and_negative_overlap(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use Ruff for Python linting."},
            {"statement": "Do not use Ruff for Python linting."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.12

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    stored_relations = relations(database)
    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_CONFLICTS
    assert result.assessment.related_memory_id == promoted_id
    assert result.assessment.confidence >= 0.8
    assert len(stored_relations) == 1
    assert stored_relations[0].relation_type == DURABLE_MEMORY_RELATION_TYPE_CONFLICTS


def test_supersedes_relation_persists_without_status_or_archive_mutation(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use Poetry for Python packaging."},
            {"statement": "Use uv instead of Poetry for Python packaging."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.1

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    stored_relations = relations(database)
    with database.session() as session:
        promoted = session.get(DurableMemoryItem, promoted_id)
        candidate = session.get(DurableMemoryItem, candidate_id)
        assert promoted is not None
        assert candidate is not None
        assert promoted.status == DURABLE_MEMORY_STATUS_PROMOTED
        assert promoted.archived_reason is None
        assert promoted.superseded_by_id is None
        assert candidate.status == DURABLE_MEMORY_STATUS_CANDIDATE
        assert candidate.archived_reason is None
        assert candidate.superseded_by_id is None

    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES
    assert result.assessment.related_memory_id == promoted_id
    assert result.assessment.confidence >= 0.8
    assert len(stored_relations) == 1
    assert stored_relations[0].relation_type == DURABLE_MEMORY_RELATION_TYPE_SUPERSEDES


def test_unresolvable_projection_hits_are_ignored_and_can_produce_novel(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Use deterministic relation assessment."}])
    projection = FakeDurableProjection()
    projection.injected_hits = [
        ProjectionHit("missing-id", "missing id", {}, 0.01),
        ProjectionHit("stale-id", "stale id", {"durable_memory_id": 9999}, 0.02),
    ]

    with database.session() as session:
        result = assess_durable_memory_relations(session, candidate_id, projection)

    assert result.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_NOVEL
    assert result.resolved_hit_count == 0
    assert relations(database) == []


def test_missing_candidate_memory_raises_not_found(database: Database) -> None:
    projection = FakeDurableProjection()

    with database.session() as session:
        with pytest.raises(DurableMemoryNotFoundError):
            assess_durable_memory_relations(session, memory_id=9999, projection=projection)


def test_repeated_assessment_updates_existing_relation_without_duplicate(database: Database) -> None:
    promoted_id, candidate_id = create_memory_fixture(
        database,
        [
            {"status": DURABLE_MEMORY_STATUS_PROMOTED, "statement": "Use SQLite before relation classification."},
            {"statement": "Use SQLite before relation classification."},
        ],
    )
    projection = FakeDurableProjection()
    projection.distances[f"durable_memory:{promoted_id}"] = 0.05

    with database.session() as session:
        first = assess_durable_memory_relations(session, candidate_id, projection)
        projection.distances[f"durable_memory:{promoted_id}"] = 0.1
        second = assess_durable_memory_relations(session, candidate_id, projection)

    stored_relations = relations(database)
    assert first.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_DUPLICATE
    assert second.assessment.relation_type == DURABLE_MEMORY_RELATION_TYPE_DUPLICATE
    assert len(stored_relations) == 1
    assert stored_relations[0].similarity_score == 0.9


def test_projection_failure_marks_record_failed_and_raises_safe_error(database: Database) -> None:
    (candidate_id,) = create_memory_fixture(database, [{"statement": "Projection failures are persisted safely."}])
    projection = FakeDurableProjection(should_fail=True)

    with database.session() as session:
        candidate = session.get(DurableMemoryItem, candidate_id)
        assert candidate is not None
        with pytest.raises(DurableMemoryProjectionError) as error_info:
            project_durable_memory_record(session, candidate, projection)

    stored_records = records(database)
    assert len(stored_records) == 1
    assert stored_records[0].status == MEMORY_PROJECTION_STATUS_FAILED
    assert stored_records[0].embedding_model is None
    assert stored_records[0].last_error is not None
    assert len(stored_records[0].last_error) == 500
    assert error_info.value.safe_error == stored_records[0].last_error
