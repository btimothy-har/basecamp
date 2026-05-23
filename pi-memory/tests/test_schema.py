from pathlib import Path

import pytest
from pi_memory.db.constants import (
    ACTIVITY_KIND_USER_TEXT,
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ACTIVITY_TEXT_STATUS_PENDING,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_RUNNING,
    DURABLE_MEMORY_ARCHIVED_REASON_STALE,
    DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED,
    DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
    DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    DURABLE_MEMORY_STATUS_ARCHIVED,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    EPISODE_INTERPRETATION_STATUS_COMPLETED,
    EPISODE_STATUS_CLOSED,
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_QUEUED,
    MEMORY_LAYER_LONG_TERM,
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_PENDING,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
    SOURCE_ORIGIN_UNKNOWN,
)
from pi_memory.db.database import Database
from pi_memory.db.models import (
    ActivityUnit,
    AnalysisRun,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemoryRelation,
    DurableMemorySource,
    Episode,
    EpisodeInterpretationSnapshot,
    EpisodeManifest,
    Job,
    MemoryProjectionRecord,
    MemorySession,
    Observation,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path):
    database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        database.initialize()
        yield database
    finally:
        database.close_if_open()


def create_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/workspace")
        transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
        session.add(transcript)
        session.flush()
        return transcript.id


def create_analysis_run(database: Database) -> tuple[int, int, int]:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1", cwd="/workspace")
        transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
        analysis_run = AnalysisRun(session=memory_session, transcript=transcript)
        session.add(analysis_run)
        session.flush()
        return memory_session.id, transcript.id, analysis_run.id


def create_interpretation_snapshot(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
        )
        session.add(snapshot)
        session.flush()
        return snapshot.id


def create_interpretation_snapshot_and_quality_report(database: Database) -> tuple[int, int, int, int | None]:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
        )
        quality_report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
        )
        session.add(quality_report)
        session.flush()
        return memory_session.id, snapshot.id, quality_report.id, transcript.id


def test_initialize_creates_pi_transcript_schema_tables(database: Database) -> None:
    inspector = inspect(database.engine)
    table_names = set(inspector.get_table_names())

    assert {
        "jobs",
        "sessions",
        "transcripts",
        "observations",
        "transcript_entries",
        "analysis_runs",
        "activity_units",
        "episodes",
        "episode_manifests",
        "episode_interpretation_snapshots",
        "session_snapshot_shells",
        "session_interpretation_snapshots",
        "session_interpretation_quality_reports",
        "durable_memory_items",
        "durable_memory_sources",
        "durable_memory_relations",
        "memory_projection_records",
        "durable_memory_audit_events",
    }.issubset(table_names)


def test_initialize_does_not_create_out_of_scope_memory_tables(database: Database) -> None:
    inspector = inspect(database.engine)
    table_names = set(inspector.get_table_names())
    forbidden_prefixes = (
        "artifacts",
        "candidates",
        "graph",
        "memories",
        "memory_artifacts",
        "memory_graph",
        "artifact_",
        "promotions",
        "promotion_",
        "embeddings",
        "chroma",
    )

    assert not {name for name in table_names if name.startswith(forbidden_prefixes)}


def test_initialize_keeps_transcript_entries_fts_virtual_table(database: Database) -> None:
    with database.engine.connect() as connection:
        create_sql = connection.execute(
            text(
                """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table' AND name = 'transcript_entries_fts'
                """,
            ),
        ).scalar_one()

    assert "CREATE VIRTUAL TABLE" in create_sql.upper()
    assert "FTS5" in create_sql.upper()


def test_fresh_schema_includes_transcript_lineage_columns_indexes_and_constraints(database: Database) -> None:
    inspector = inspect(database.engine)

    columns = {column["name"]: column for column in inspector.get_columns("transcripts")}
    indexes = {index["name"] for index in inspector.get_indexes("transcripts")}
    foreign_keys = inspector.get_foreign_keys("transcripts")
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("transcripts")}

    assert columns["parent_transcript_path"]["nullable"] is True
    assert columns["parent_transcript_id"]["nullable"] is True
    assert {
        "ix_transcripts_parent_transcript_id",
        "ix_transcripts_parent_transcript_path",
    }.issubset(indexes)
    assert any(
        foreign_key["constrained_columns"] == ["parent_transcript_id"]
        and foreign_key["referred_table"] == "transcripts"
        and foreign_key["options"].get("ondelete") == "SET NULL"
        for foreign_key in foreign_keys
    )
    assert {
        "ck_transcripts_parent_not_self",
        "ck_transcripts_parent_id_requires_path",
        "ck_transcripts_parent_path_non_empty",
    }.issubset(constraints)


def test_durable_memory_schema_includes_indexes_foreign_keys_and_constraints(database: Database) -> None:
    inspector = inspect(database.engine)

    item_constraints = {constraint["name"] for constraint in inspector.get_check_constraints("durable_memory_items")}
    item_indexes = {index["name"] for index in inspector.get_indexes("durable_memory_items")}
    item_foreign_keys = inspector.get_foreign_keys("durable_memory_items")
    source_indexes = {index["name"] for index in inspector.get_indexes("durable_memory_sources")}
    source_foreign_keys = inspector.get_foreign_keys("durable_memory_sources")
    relation_constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("durable_memory_relations")
    }
    audit_indexes = {index["name"] for index in inspector.get_indexes("durable_memory_audit_events")}

    assert {
        "ck_durable_memory_items_status_valid",
        "ck_durable_memory_items_archived_reason_matches_status",
        "ck_durable_memory_items_superseded_by_matches_reason",
        "ck_durable_memory_items_not_self_superseded",
        "ck_durable_memory_items_confidence_range",
        "ck_durable_memory_items_content_hash_non_empty",
        "ck_durable_memory_items_schema_version_positive",
    }.issubset(item_constraints)
    assert {
        "ix_durable_memory_items_session_status",
        "ix_durable_memory_items_snapshot_id",
        "ix_durable_memory_items_quality_report_id",
        "ix_durable_memory_items_content_hash",
    }.issubset(item_indexes)
    assert any(
        foreign_key["constrained_columns"] == ["transcript_id"]
        and foreign_key["referred_table"] == "transcripts"
        and foreign_key["options"].get("ondelete") == "SET NULL"
        for foreign_key in item_foreign_keys
    )
    assert any(
        foreign_key["constrained_columns"] == ["snapshot_id"]
        and foreign_key["referred_table"] == "session_interpretation_snapshots"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in item_foreign_keys
    )
    assert {
        "ix_durable_memory_sources_memory_id",
        "ix_durable_memory_sources_snapshot_id",
        "ix_durable_memory_sources_source_ref",
    }.issubset(source_indexes)
    assert any(
        foreign_key["constrained_columns"] == ["activity_unit_id"]
        and foreign_key["referred_table"] == "activity_units"
        and foreign_key["options"].get("ondelete") == "SET NULL"
        for foreign_key in source_foreign_keys
    )
    assert {
        "ck_durable_memory_relations_relation_type_valid",
        "ck_durable_memory_relations_not_self",
        "ck_durable_memory_relations_similarity_score_range",
        "ck_durable_memory_relations_confidence_range",
    }.issubset(relation_constraints)
    assert "ix_durable_memory_audit_events_memory_created" in audit_indexes


def test_memory_projection_schema_includes_indexes_foreign_keys_and_constraints(database: Database) -> None:
    inspector = inspect(database.engine)

    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("memory_projection_records")}
    indexes = {index["name"] for index in inspector.get_indexes("memory_projection_records")}
    foreign_keys = inspector.get_foreign_keys("memory_projection_records")
    unique_constraints = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("memory_projection_records")
    }

    assert {
        "ck_memory_projection_records_record_type_valid",
        "ck_memory_projection_records_memory_layer_valid",
        "ck_memory_projection_records_record_type_invariants",
        "ck_memory_projection_records_status_valid",
        "ck_memory_projection_records_source_id_positive",
        "ck_memory_projection_records_content_hash_non_empty",
    }.issubset(constraints)
    assert {
        "ix_memory_projection_records_collection_status",
        "ix_memory_projection_records_source",
        "ix_memory_projection_records_snapshot_id",
        "ix_memory_projection_records_durable_memory_id",
    }.issubset(indexes)
    assert ("collection_name", "chroma_id") in unique_constraints
    assert ("collection_name", "record_key") in unique_constraints
    assert any(
        foreign_key["constrained_columns"] == ["durable_memory_id"]
        and foreign_key["referred_table"] == "durable_memory_items"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in foreign_keys
    )


def test_durable_memory_defaults_relationships_and_projection_defaults(database: Database) -> None:
    session_id, snapshot_id, quality_report_id, transcript_id = create_interpretation_snapshot_and_quality_report(
        database
    )

    with database.session() as session:
        memory = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            claim_kind="preference",
            statement="Prefer durable facts in SQLite.",
            confidence=0.75,
            content_hash="hash-1",
        )
        related_memory = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=1,
            claim_kind="preference",
            statement="SQLite is canonical for memory.",
            content_hash="hash-2",
        )
        session.add_all([memory, related_memory])
        session.flush()
        source = DurableMemorySource(
            memory=memory,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            source_ref="claim:0",
        )
        relation = DurableMemoryRelation(
            memory=memory,
            related_memory=related_memory,
            relation_type=DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
            similarity_score=0.8,
            confidence=0.9,
        )
        projection = MemoryProjectionRecord(
            chroma_id="durable:1",
            record_key="durable-memory:hash-1",
            record_type=MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
            memory_layer=MEMORY_LAYER_LONG_TERM,
            source_table="durable_memory_items",
            source_id=memory.id,
            durable_memory=memory,
            content_hash="hash-1",
        )
        audit_event = DurableMemoryAuditEvent(
            memory=memory,
            event_type="created",
            to_status=DURABLE_MEMORY_STATUS_CANDIDATE,
        )
        session.add_all([source, relation, projection, audit_event])
        session.flush()
        session.refresh(memory)
        session.refresh(source)
        session.refresh(projection)
        session.refresh(audit_event)

        assert memory.status == DURABLE_MEMORY_STATUS_CANDIDATE
        assert memory.evaluation_json == {}
        assert memory.relation_summary_json == {}
        assert memory.metadata_json == {}
        assert memory.schema_version == 1
        assert source.source_origin == SOURCE_ORIGIN_UNKNOWN
        assert source.source_kind == DURABLE_MEMORY_SOURCE_KIND_CLAIM
        assert source.metadata_json == {}
        assert projection.collection_name == MEMORY_PROJECTION_COLLECTION_NAME
        assert projection.status == MEMORY_PROJECTION_STATUS_PENDING
        assert projection.recall_visible is False
        assert projection.relation_visible is False
        assert audit_event.details_json == {}
        assert memory.sources == [source]
        assert memory.relations == [relation]
        assert memory.projection_records == [projection]
        assert memory.audit_events == [audit_event]


def test_durable_memory_constraints_reject_invalid_rows(database: Database) -> None:
    session_id, snapshot_id, quality_report_id, transcript_id = create_interpretation_snapshot_and_quality_report(
        database
    )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                status="invalid",
                claim_index=0,
                claim_kind="preference",
                statement="Invalid status.",
                content_hash="hash-invalid-status",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                status=DURABLE_MEMORY_STATUS_CANDIDATE,
                archived_reason=DURABLE_MEMORY_ARCHIVED_REASON_STALE,
                claim_index=0,
                claim_kind="preference",
                statement="Non-archived rows cannot carry archived reasons.",
                content_hash="hash-invalid-archived-reason",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                status=DURABLE_MEMORY_STATUS_ARCHIVED,
                claim_index=0,
                claim_kind="preference",
                statement="Archived rows need an archived reason.",
                content_hash="hash-invalid-archived-missing-reason",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                status=DURABLE_MEMORY_STATUS_ARCHIVED,
                archived_reason=DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED,
                claim_index=0,
                claim_kind="preference",
                statement="Superseded archived rows need a replacement.",
                content_hash="hash-invalid-superseded",
            ),
        )

    with database.session() as session:
        replacement = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=1,
            claim_kind="preference",
            statement="Replacement memory.",
            content_hash="hash-replacement",
        )
        session.add(replacement)
        session.flush()
        replacement_id = replacement.id

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                superseded_by_id=replacement_id,
                claim_index=0,
                claim_kind="preference",
                statement="Only superseded archived rows can reference a replacement.",
                content_hash="hash-invalid-superseded-by",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                status_reason="",
                claim_index=0,
                claim_kind="preference",
                statement="Empty status reasons are invalid.",
                content_hash="hash-invalid-status-reason",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                claim_index=-1,
                claim_kind="preference",
                statement="Negative claim indexes are invalid.",
                content_hash="hash-invalid-claim-index",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryItem(
                session_id=session_id,
                transcript_id=transcript_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                claim_index=0,
                claim_kind="preference",
                statement="Out of range confidence is invalid.",
                confidence=1.5,
                content_hash="hash-invalid-confidence",
            ),
        )


def test_durable_memory_accepts_archived_reason_states(database: Database) -> None:
    session_id, snapshot_id, quality_report_id, transcript_id = create_interpretation_snapshot_and_quality_report(
        database
    )

    with database.session() as session:
        replacement = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            claim_kind="preference",
            statement="Replacement memory.",
            content_hash="hash-archive-replacement",
        )
        stale = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            status=DURABLE_MEMORY_STATUS_ARCHIVED,
            archived_reason=DURABLE_MEMORY_ARCHIVED_REASON_STALE,
            claim_index=1,
            claim_kind="preference",
            statement="Archived stale memory.",
            content_hash="hash-archived-stale",
        )
        session.add_all([replacement, stale])
        session.flush()
        superseded = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            status=DURABLE_MEMORY_STATUS_ARCHIVED,
            archived_reason=DURABLE_MEMORY_ARCHIVED_REASON_SUPERSEDED,
            superseded_by_id=replacement.id,
            claim_index=2,
            claim_kind="preference",
            statement="Archived superseded memory.",
            content_hash="hash-archived-superseded",
        )
        session.add(superseded)
        session.flush()
        session.refresh(stale)
        session.refresh(superseded)

        assert stale.archived_reason == DURABLE_MEMORY_ARCHIVED_REASON_STALE
        assert stale.superseded_by_id is None
        assert superseded.superseded_by_id == replacement.id


def test_durable_memory_source_relation_and_audit_constraints(database: Database) -> None:
    session_id, snapshot_id, quality_report_id, transcript_id = create_interpretation_snapshot_and_quality_report(
        database
    )

    with database.session() as session:
        memory = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            claim_kind="preference",
            statement="A sourceable memory.",
            content_hash="hash-sourceable",
        )
        related_memory = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=1,
            claim_kind="preference",
            statement="A related memory.",
            content_hash="hash-related-sourceable",
        )
        session.add_all([memory, related_memory])
        session.flush()
        memory_id = memory.id
        related_memory_id = related_memory.id

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemorySource(
                memory_id=memory_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                claim_index=0,
                source_ref="",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemorySource(
                memory_id=memory_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                claim_index=0,
                source_ref="claim:0",
                source_origin="remote",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemorySource(
                memory_id=memory_id,
                snapshot_id=snapshot_id,
                quality_report_id=quality_report_id,
                claim_index=0,
                source_ref="claim:0",
                source_kind="audit",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryRelation(
                memory_id=memory_id,
                related_memory_id=memory_id,
                relation_type=DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            DurableMemoryRelation(
                memory_id=memory_id,
                related_memory_id=related_memory_id,
                relation_type=DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
                similarity_score=1.5,
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(DurableMemoryAuditEvent(memory_id=memory_id, event_type=""))

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(DurableMemoryAuditEvent(memory_id=memory_id, event_type="invalid-status", from_status="bogus"))


def test_memory_projection_records_enforce_type_invariants(database: Database) -> None:
    session_id, snapshot_id, quality_report_id, transcript_id = create_interpretation_snapshot_and_quality_report(
        database
    )

    with database.session() as session:
        memory = DurableMemoryItem(
            session_id=session_id,
            transcript_id=transcript_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            claim_kind="preference",
            statement="A projectable memory.",
            content_hash="hash-projectable",
        )
        session.add(memory)
        session.flush()
        memory_id = memory.id

    with database.session() as session:
        projection = MemoryProjectionRecord(
            chroma_id="session-claim:0",
            record_key="session-claim:0",
            record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
            memory_layer=MEMORY_LAYER_SHORT_TERM,
            source_table="session_interpretation_snapshots",
            source_id=snapshot_id,
            snapshot_id=snapshot_id,
            quality_report_id=quality_report_id,
            claim_index=0,
            content_hash="hash-session-claim",
        )
        session.add(projection)
        session.flush()
        session.refresh(projection)

        assert projection.collection_name == MEMORY_PROJECTION_COLLECTION_NAME
        assert projection.status == MEMORY_PROJECTION_STATUS_PENDING

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            MemoryProjectionRecord(
                chroma_id="session-claim:0",
                record_key="session-claim:duplicate-chroma-id",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
                memory_layer=MEMORY_LAYER_SHORT_TERM,
                source_table="session_interpretation_snapshots",
                source_id=snapshot_id,
                snapshot_id=snapshot_id,
                claim_index=1,
                content_hash="hash-duplicate-chroma-id",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            MemoryProjectionRecord(
                chroma_id="session-claim-missing-snapshot",
                record_key="session-claim-missing-snapshot",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
                memory_layer=MEMORY_LAYER_SHORT_TERM,
                source_table="session_interpretation_snapshots",
                source_id=snapshot_id,
                claim_index=0,
                content_hash="hash-invalid-missing-snapshot",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            MemoryProjectionRecord(
                chroma_id="session-claim-invalid-source-id",
                record_key="session-claim-invalid-source-id",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
                memory_layer=MEMORY_LAYER_SHORT_TERM,
                source_table="session_interpretation_snapshots",
                source_id=0,
                snapshot_id=snapshot_id,
                claim_index=0,
                content_hash="hash-invalid-source-id",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            MemoryProjectionRecord(
                chroma_id="session-claim-invalid",
                record_key="session-claim-invalid",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
                memory_layer=MEMORY_LAYER_LONG_TERM,
                source_table="session_interpretation_snapshots",
                source_id=snapshot_id,
                snapshot_id=snapshot_id,
                claim_index=0,
                content_hash="hash-invalid-session-claim",
            ),
        )

    with pytest.raises(IntegrityError), database.session() as session:
        session.add(
            MemoryProjectionRecord(
                chroma_id="durable-invalid",
                record_key="durable-invalid",
                record_type=MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
                memory_layer=MEMORY_LAYER_LONG_TERM,
                source_table="durable_memory_items",
                source_id=memory_id,
                durable_memory_id=memory_id,
                claim_index=0,
                content_hash="hash-invalid-durable",
            ),
        )


def test_job_defaults_are_applied(database: Database) -> None:
    with database.session() as session:
        job = Job(kind=JOB_KIND_PROCESS_TRANSCRIPT)
        session.add(job)
        session.flush()
        session.refresh(job)

        assert job.kind == JOB_KIND_PROCESS_TRANSCRIPT
        assert job.status == JOB_STATUS_QUEUED
        assert job.payload_json == {}
        assert job.priority == 0
        assert job.due_at is not None
        assert job.attempts == 0
        assert job.max_attempts == 3
        assert job.created_at is not None
        assert job.updated_at is not None


def test_analysis_run_defaults_are_applied(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(path="/tmp/pi/transcript.jsonl", session=memory_session)
        analysis_run = AnalysisRun(session=memory_session, transcript=transcript)
        session.add(analysis_run)
        session.flush()
        session.refresh(analysis_run)

        assert analysis_run.analysis_kind == ANALYSIS_KIND_TRANSCRIPT_STRUCTURE
        assert analysis_run.status == ANALYSIS_STATUS_RUNNING
        assert analysis_run.analyzed_through_byte_offset == 0
        assert analysis_run.activity_count == 0
        assert analysis_run.episode_count == 0
        assert analysis_run.manifest_count == 0
        assert analysis_run.diagnostics_json == {}
        assert analysis_run.started_at is not None
        assert analysis_run.created_at is not None
        assert analysis_run.updated_at is not None


def test_session_snapshot_shell_defaults_are_applied(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot_shell = SessionSnapshotShell(session=memory_session)
        session.add(snapshot_shell)
        session.flush()
        session.refresh(snapshot_shell)

        assert snapshot_shell.status == SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION
        assert snapshot_shell.analyzed_through_byte_offset == 0
        assert snapshot_shell.activity_count == 0
        assert snapshot_shell.episode_count == 0
        assert snapshot_shell.manifest_count == 0
        assert snapshot_shell.tool_pair_count == 0
        assert snapshot_shell.snapshot_json == {}
        assert snapshot_shell.created_at is not None
        assert snapshot_shell.updated_at is not None


def test_session_interpretation_snapshot_defaults_are_applied(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        job = Job(kind=JOB_KIND_INTERPRET_SESSION)
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            job=job,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
        )
        session.add(snapshot)
        session.flush()
        session.refresh(snapshot)

        assert snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED
        assert snapshot.blocked_reason is None
        assert snapshot.analyzed_through_byte_offset == 0
        assert snapshot.origin_counts_json == {}
        assert snapshot.claim_source_activity_count == 0
        assert snapshot.interpretation_json == {}
        assert snapshot.citations_json == []
        assert snapshot.model_metadata_json == {}
        assert snapshot.prompt_version is None
        assert snapshot.schema_version == 1
        assert snapshot.created_at is not None
        assert snapshot.updated_at is not None
        assert memory_session.session_interpretation_snapshot == snapshot
        assert job.session_interpretation_snapshots == [snapshot]


def test_episode_interpretation_snapshot_defaults_are_applied(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl")
        analysis_run = AnalysisRun(session=memory_session, transcript=transcript)
        episode = Episode(
            session=memory_session,
            transcript=transcript,
            analysis_run=analysis_run,
            ordinal=0,
            byte_start=0,
            byte_end=1,
            status=EPISODE_STATUS_CLOSED,
            close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
        )
        job = Job(kind=JOB_KIND_INTERPRET_SESSION)
        snapshot = EpisodeInterpretationSnapshot(
            session=memory_session,
            transcript=transcript,
            analysis_run=analysis_run,
            episode=episode,
            job=job,
            status=EPISODE_INTERPRETATION_STATUS_COMPLETED,
        )
        session.add(snapshot)
        session.flush()
        session.refresh(snapshot)

        assert snapshot.status == EPISODE_INTERPRETATION_STATUS_COMPLETED
        assert snapshot.episode_ordinal == 0
        assert snapshot.activity_count == 0
        assert snapshot.claim_source_activity_count == 0
        assert snapshot.analyzed_through_byte_offset == 0
        assert snapshot.interpretation_json == {}
        assert snapshot.citations_json == []
        assert snapshot.model_metadata_json == {}
        assert snapshot.failure_metadata_json == {}
        assert snapshot.prompt_version is None
        assert snapshot.schema_version == 1
        assert snapshot.created_at is not None
        assert snapshot.updated_at is not None
        assert memory_session.episode_interpretation_snapshots == [snapshot]
        assert transcript.episode_interpretation_snapshots == [snapshot]
        assert analysis_run.episode_interpretation_snapshots == [snapshot]
        assert episode.interpretation_snapshot == snapshot
        assert job.episode_interpretation_snapshots == [snapshot]


def test_fresh_schema_includes_episode_interpretation_snapshot_indexes_and_constraints(
    database: Database,
) -> None:
    inspector = inspect(database.engine)

    columns = {column["name"]: column for column in inspector.get_columns("episode_interpretation_snapshots")}
    indexes = {index["name"] for index in inspector.get_indexes("episode_interpretation_snapshots")}
    constraints = {
        constraint["name"] for constraint in inspector.get_check_constraints("episode_interpretation_snapshots")
    }

    assert columns["failure_metadata_json"]["nullable"] is False
    assert {
        "ix_episode_interpretation_snapshots_analysis_ordinal",
        "ix_episode_interpretation_snapshots_status_updated_at",
        "ix_episode_interpretation_snapshots_job_id",
    }.issubset(indexes)
    assert {
        "ck_episode_interpretation_snapshots_status_valid",
        "ck_episode_interpretation_snapshots_claim_source_activity_count_non_negative",
        "ck_episode_interpretation_snapshots_schema_version_positive",
    }.issubset(constraints)


def test_session_interpretation_quality_report_defaults_and_relationships_are_applied(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
        )
        job = Job(kind=JOB_KIND_ASSESS_INTERPRETATION_QUALITY)
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            job=job,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
        )
        session.add(report)
        session.flush()
        session.refresh(report)

        assert report.snapshot == snapshot
        assert snapshot.quality_report == report
        assert report.job == job
        assert job.session_interpretation_quality_reports == [report]
        assert report.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
        assert report.quality_reason is None
        assert report.derivation_status == SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT
        assert report.deterministic_status == SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED
        assert report.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
        assert report.promotable is False
        assert report.deterministic_findings_json == []
        assert report.semantic_findings_json == []
        assert report.claim_assessments_json == []
        assert report.missing_high_signal_items_json == []
        assert report.model_metadata_json == {}
        assert report.assessment_metadata_json == {}
        assert report.prompt_version is None
        assert report.schema_version == 1
        assert report.created_at is not None
        assert report.updated_at is not None


def test_session_interpretation_quality_report_accepts_non_healthy_reason(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with database.session() as session:
        report = SessionInterpretationQualityReport(
            snapshot_id=snapshot_id,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
            quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
        )
        session.add(report)
        session.flush()
        session.refresh(report)

        assert report.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_status", "unknown"),
        ("derivation_status", "stale"),
        ("deterministic_status", "partial"),
        ("semantic_status", "unknown"),
    ],
)
def test_session_interpretation_quality_report_rejects_invalid_enums(
    database: Database,
    field: str,
    value: str,
) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            kwargs = {
                "snapshot_id": snapshot_id,
                "quality_status": SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                field: value,
            }
            session.add(SessionInterpretationQualityReport(**kwargs))


def test_session_interpretation_quality_report_rejects_invalid_reason(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot_id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
                    quality_reason="missing_citations",
                ),
            )


def test_session_interpretation_quality_report_requires_reason_for_non_healthy_status(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot_id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_DEGRADED,
                ),
            )


def test_session_interpretation_quality_report_rejects_reason_for_healthy_status(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot_id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    quality_reason=SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_DEGRADED,
                ),
            )


def test_session_interpretation_quality_report_rejects_invalid_schema_version(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                SessionInterpretationQualityReport(
                    snapshot_id=snapshot_id,
                    quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    schema_version=0,
                ),
            )


def test_only_one_session_interpretation_quality_report_per_snapshot(database: Database) -> None:
    snapshot_id = create_interpretation_snapshot(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    SessionInterpretationQualityReport(
                        snapshot_id=snapshot_id,
                        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    ),
                    SessionInterpretationQualityReport(
                        snapshot_id=snapshot_id,
                        quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
                    ),
                ],
            )


def test_session_interpretation_snapshot_delete_cascades_to_quality_report(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_COMPLETED,
        )
        report = SessionInterpretationQualityReport(
            snapshot=snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
        )
        session.add(report)
        session.flush()
        report_id = report.id

        session.delete(snapshot)
        session.flush()

        assert session.get(SessionInterpretationQualityReport, report_id) is None


def test_session_interpretation_snapshot_accepts_blocked_reason(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_BLOCKED,
            blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
        )
        session.add(snapshot)
        session.flush()
        session.refresh(snapshot)

        assert snapshot.blocked_reason == SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY


def test_session_interpretation_snapshot_requires_status(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(SessionInterpretationSnapshot(session=memory_session))


def test_session_interpretation_snapshot_rejects_invalid_status(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(
                SessionInterpretationSnapshot(
                    session=memory_session,
                    status="running",
                ),
            )


def test_session_interpretation_snapshot_rejects_invalid_blocked_reason(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(
                SessionInterpretationSnapshot(
                    session=memory_session,
                    status=SESSION_INTERPRETATION_STATUS_BLOCKED,
                    blocked_reason="llm_timeout",
                ),
            )


def test_session_interpretation_snapshot_requires_blocked_reason_for_blocked_status(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(
                SessionInterpretationSnapshot(
                    session=memory_session,
                    status=SESSION_INTERPRETATION_STATUS_BLOCKED,
                ),
            )


def test_session_interpretation_snapshot_rejects_blocked_reason_for_completed_status(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(
                SessionInterpretationSnapshot(
                    session=memory_session,
                    status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                    blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
                ),
            )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("analyzed_through_byte_offset", -1),
        ("claim_source_activity_count", -1),
        ("schema_version", 0),
    ],
)
def test_session_interpretation_snapshot_rejects_invalid_counts(
    database: Database,
    field: str,
    value: int,
) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(
                SessionInterpretationSnapshot(
                    session=memory_session,
                    status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                    **{field: value},
                ),
            )


def test_only_one_session_interpretation_snapshot_per_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add_all(
                [
                    SessionInterpretationSnapshot(
                        session=memory_session,
                        status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                    ),
                    SessionInterpretationSnapshot(
                        session=memory_session,
                        status=SESSION_INTERPRETATION_STATUS_COMPLETED,
                    ),
                ],
            )


def test_analysis_run_rejects_invalid_status(database: Database) -> None:
    session_id, transcript_id, _ = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(AnalysisRun(session_id=session_id, transcript_id=transcript_id, status="invalid"))


def test_fresh_schema_includes_activity_unit_source_origin_column_index_and_constraint(database: Database) -> None:
    inspector = inspect(database.engine)

    columns = {column["name"]: column for column in inspector.get_columns("activity_units")}
    indexes = {index["name"] for index in inspector.get_indexes("activity_units")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("activity_units")}

    assert columns["source_origin"]["nullable"] is False
    assert "unknown" in str(columns["source_origin"].get("default"))
    assert "ix_activity_units_source_origin" in indexes
    assert "ck_activity_units_source_origin_valid" in constraints


def test_fresh_schema_includes_activity_text_columns_indexes_and_constraints(database: Database) -> None:
    inspector = inspect(database.engine)

    columns = {column["name"]: column for column in inspector.get_columns("activity_units")}
    indexes = {index["name"] for index in inspector.get_indexes("activity_units")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("activity_units")}

    assert columns["activity_text"]["nullable"] is True
    assert columns["activity_text_kind"]["nullable"] is False
    assert ACTIVITY_TEXT_KIND_UNAVAILABLE in str(columns["activity_text_kind"].get("default"))
    assert columns["activity_text_status"]["nullable"] is False
    assert ACTIVITY_TEXT_STATUS_PENDING in str(columns["activity_text_status"].get("default"))
    assert columns["activity_text_metadata_json"]["nullable"] is False
    assert "{}" in str(columns["activity_text_metadata_json"].get("default"))
    assert "ix_activity_units_analysis_run_text_status" in indexes
    assert {
        "ck_activity_units_activity_text_kind_valid",
        "ck_activity_units_activity_text_status_valid",
        "ck_activity_units_completed_activity_text_present",
    }.issubset(constraints)


def test_activity_unit_defaults_are_applied(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with database.session() as session:
        activity_unit = ActivityUnit(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            ordinal=0,
            kind=ACTIVITY_KIND_USER_TEXT,
            byte_start=0,
            byte_end=1,
        )
        session.add(activity_unit)
        session.flush()
        session.refresh(activity_unit)

        assert activity_unit.source_entry_ids_json == []
        assert activity_unit.raw_text_available is True
        assert activity_unit.text_char_count == 0
        assert activity_unit.result_text_byte_count == 0
        assert activity_unit.result_text_line_count == 0
        assert activity_unit.receipt_json == {}
        assert activity_unit.source_metadata_json == {}
        assert activity_unit.source_origin == SOURCE_ORIGIN_UNKNOWN
        assert activity_unit.activity_text is None
        assert activity_unit.activity_text_kind == ACTIVITY_TEXT_KIND_UNAVAILABLE
        assert activity_unit.activity_text_status == ACTIVITY_TEXT_STATUS_PENDING
        assert activity_unit.activity_text_metadata_json == {}
        assert activity_unit.created_at is not None
        assert activity_unit.updated_at is not None


def test_episode_defaults_are_applied(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with database.session() as session:
        episode = Episode(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            ordinal=0,
            close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
            byte_start=0,
            byte_end=1,
        )
        session.add(episode)
        session.flush()
        session.refresh(episode)

        assert episode.status == EPISODE_STATUS_CLOSED
        assert episode.activity_count == 0
        assert episode.message_count == 0
        assert episode.tool_pair_count == 0
        assert episode.boundary_metadata == {}
        assert episode.created_at is not None
        assert episode.updated_at is not None


def test_fresh_schema_includes_episode_manifest_tool_result_text_byte_count_constraint(
    database: Database,
) -> None:
    inspector = inspect(database.engine)

    columns = {column["name"]: column for column in inspector.get_columns("episode_manifests")}
    constraints = {constraint["name"] for constraint in inspector.get_check_constraints("episode_manifests")}

    assert columns["tool_result_text_byte_count"]["nullable"] is False
    assert "0" in str(columns["tool_result_text_byte_count"].get("default"))
    assert "ck_episode_manifests_tool_result_text_byte_count_non_negative" in constraints
    assert "omitted_raw_text_bytes" not in columns


def test_episode_manifest_defaults_are_applied(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with database.session() as session:
        episode = Episode(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            ordinal=0,
            close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
            byte_start=0,
            byte_end=1,
        )
        session.add(episode)
        session.flush()
        manifest = EpisodeManifest(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            episode_id=episode.id,
            byte_start=0,
            byte_end=1,
        )
        session.add(manifest)
        session.flush()
        session.refresh(manifest)

        assert manifest.manifest_version == 1
        assert manifest.activity_count == 0
        assert manifest.tool_pair_count == 0
        assert manifest.activity_map_json == {}
        assert manifest.source_spans_json == []
        assert manifest.tool_result_text_byte_count == 0
        assert manifest.created_at is not None
        assert manifest.updated_at is not None


def test_activity_unit_rejects_invalid_source_origin(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ActivityUnit(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    kind=ACTIVITY_KIND_USER_TEXT,
                    byte_start=0,
                    byte_end=1,
                    source_origin="remote",
                ),
            )


def test_activity_unit_rejects_invalid_kind(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ActivityUnit(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    kind="semantic_summary",
                    byte_start=0,
                    byte_end=1,
                ),
            )


def test_activity_unit_rejects_invalid_activity_text_kind(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ActivityUnit(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    kind=ACTIVITY_KIND_USER_TEXT,
                    byte_start=0,
                    byte_end=1,
                    activity_text_kind="raw_json",
                ),
            )


def test_activity_unit_rejects_invalid_activity_text_status(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ActivityUnit(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    kind=ACTIVITY_KIND_USER_TEXT,
                    byte_start=0,
                    byte_end=1,
                    activity_text_status="waiting_for_worker",
                ),
            )


def test_activity_unit_requires_activity_text_when_completed(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                ActivityUnit(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    kind=ACTIVITY_KIND_USER_TEXT,
                    byte_start=0,
                    byte_end=1,
                    activity_text_status=ACTIVITY_TEXT_STATUS_COMPLETED,
                ),
            )


def test_activity_unit_rejects_duplicate_ordinal_in_analysis_run(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    ActivityUnit(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        ordinal=0,
                        kind=ACTIVITY_KIND_USER_TEXT,
                        byte_start=0,
                        byte_end=1,
                    ),
                    ActivityUnit(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        ordinal=0,
                        kind=ACTIVITY_KIND_USER_TEXT,
                        byte_start=1,
                        byte_end=2,
                    ),
                ],
            )


def test_episode_rejects_invalid_close_reason(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                Episode(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    status=EPISODE_STATUS_CLOSED,
                    close_reason="raw_size",
                    byte_start=0,
                    byte_end=1,
                ),
            )


def test_closed_episode_requires_close_reason(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                Episode(
                    analysis_run_id=analysis_run_id,
                    session_id=session_id,
                    transcript_id=transcript_id,
                    ordinal=0,
                    status=EPISODE_STATUS_CLOSED,
                    byte_start=0,
                    byte_end=1,
                ),
            )


def test_episode_rejects_duplicate_ordinal_in_analysis_run(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    Episode(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        ordinal=0,
                        close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
                        byte_start=0,
                        byte_end=1,
                    ),
                    Episode(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        ordinal=0,
                        close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
                        byte_start=1,
                        byte_end=2,
                    ),
                ],
            )


def test_episode_manifest_is_unique_per_episode(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            episode = Episode(
                analysis_run_id=analysis_run_id,
                session_id=session_id,
                transcript_id=transcript_id,
                ordinal=0,
                close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
                byte_start=0,
                byte_end=1,
            )
            session.add(episode)
            session.flush()
            session.add_all(
                [
                    EpisodeManifest(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        episode_id=episode.id,
                        byte_start=0,
                        byte_end=1,
                    ),
                    EpisodeManifest(
                        analysis_run_id=analysis_run_id,
                        session_id=session_id,
                        transcript_id=transcript_id,
                        episode_id=episode.id,
                        byte_start=0,
                        byte_end=1,
                    ),
                ],
            )


def test_large_raw_size_metadata_does_not_create_episode_size_constraints(database: Database) -> None:
    session_id, transcript_id, analysis_run_id = create_analysis_run(database)

    with database.session() as session:
        episode = Episode(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            ordinal=0,
            status=EPISODE_STATUS_CLOSED,
            close_reason=EPISODE_CLOSE_REASON_TRANSCRIPT_END,
            byte_start=0,
            byte_end=1,
        )
        session.add(episode)
        session.flush()
        activity_unit = ActivityUnit(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            episode_id=episode.id,
            ordinal=0,
            kind=ACTIVITY_KIND_USER_TEXT,
            byte_start=0,
            byte_end=1,
            result_text_byte_count=10**12,
            result_text_line_count=10**9,
        )
        manifest = EpisodeManifest(
            analysis_run_id=analysis_run_id,
            session_id=session_id,
            transcript_id=transcript_id,
            episode_id=episode.id,
            byte_start=0,
            byte_end=1,
            source_spans_json=[{"entry_id": 1, "raw_text_bytes": 10**12}],
            tool_result_text_byte_count=10**12,
        )
        session.add_all([activity_unit, manifest])
        session.flush()
        session.refresh(activity_unit)
        session.refresh(manifest)

        assert activity_unit.result_text_byte_count == 10**12
        assert activity_unit.result_text_line_count == 10**9
        assert manifest.source_spans_json == [{"entry_id": 1, "raw_text_bytes": 10**12}]
        assert manifest.tool_result_text_byte_count == 10**12


def test_only_one_session_snapshot_shell_per_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add_all(
                [
                    SessionSnapshotShell(session=memory_session),
                    SessionSnapshotShell(session=memory_session),
                ],
            )


def test_phase_5a_indexes_exist(database: Database) -> None:
    inspector = inspect(database.engine)

    analysis_run_indexes = {index["name"] for index in inspector.get_indexes("analysis_runs")}
    activity_indexes = {index["name"] for index in inspector.get_indexes("activity_units")}
    episode_indexes = {index["name"] for index in inspector.get_indexes("episodes")}
    manifest_indexes = {index["name"] for index in inspector.get_indexes("episode_manifests")}
    snapshot_indexes = {index["name"] for index in inspector.get_indexes("session_snapshot_shells")}

    assert {
        "ix_analysis_runs_session_status",
        "ix_analysis_runs_transcript_status",
        "ix_analysis_runs_job_id",
        "ix_analysis_runs_created_at",
    }.issubset(analysis_run_indexes)
    assert {
        "ix_activity_units_analysis_run_ordinal",
        "ix_activity_units_transcript_byte_start",
        "ix_activity_units_episode_ordinal",
        "ix_activity_units_kind",
        "ix_activity_units_tool_call_id",
        "ix_activity_units_source_origin",
        "ix_activity_units_analysis_run_text_status",
    }.issubset(activity_indexes)
    assert {
        "ix_episodes_analysis_run_ordinal",
        "ix_episodes_transcript_byte_start",
        "ix_episodes_close_reason",
    }.issubset(episode_indexes)
    assert {
        "ix_episode_manifests_analysis_run_id",
        "ix_episode_manifests_transcript_byte_start",
        "ix_episode_manifests_episode_id",
    }.issubset(manifest_indexes)
    assert {"ix_session_snapshot_shells_status_updated_at"}.issubset(snapshot_indexes)


def test_phase_5b_indexes_exist(database: Database) -> None:
    inspector = inspect(database.engine)

    snapshot_indexes = {index["name"] for index in inspector.get_indexes("session_interpretation_snapshots")}

    assert {
        "ix_session_interpretation_snapshots_session_id",
        "ix_session_interpretation_snapshots_transcript_id",
        "ix_session_interpretation_snapshots_analysis_run_id",
        "ix_session_interpretation_snapshots_job_id",
        "ix_session_interpretation_snapshots_analyzed_through_entry_id",
        "ix_session_interpretation_snapshots_status_updated_at",
    }.issubset(snapshot_indexes)


def test_phase_5c_quality_report_indexes_and_foreign_keys_exist(database: Database) -> None:
    inspector = inspect(database.engine)

    report_indexes = {index["name"] for index in inspector.get_indexes("session_interpretation_quality_reports")}
    foreign_keys = inspector.get_foreign_keys("session_interpretation_quality_reports")

    assert {
        "ix_session_interpretation_quality_reports_snapshot_id",
        "ix_session_interpretation_quality_reports_quality_status_updated_at",
        "ix_session_interpretation_quality_reports_derivation_status_quality_status",
        "ix_session_interpretation_quality_reports_promotable_updated_at",
        "ix_session_interpretation_quality_reports_job_id",
    }.issubset(report_indexes)
    assert any(
        foreign_key["constrained_columns"] == ["snapshot_id"]
        and foreign_key["referred_table"] == "session_interpretation_snapshots"
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in foreign_keys
    )
    assert any(
        foreign_key["constrained_columns"] == ["job_id"]
        and foreign_key["referred_table"] == "jobs"
        and foreign_key["options"].get("ondelete") == "SET NULL"
        for foreign_key in foreign_keys
    )


def test_job_accepts_assess_interpretation_quality_kind(database: Database) -> None:
    with database.session() as session:
        job = Job(kind=JOB_KIND_ASSESS_INTERPRETATION_QUALITY)
        session.add(job)
        session.flush()
        session.refresh(job)

        assert job.kind == JOB_KIND_ASSESS_INTERPRETATION_QUALITY
        assert job.status == JOB_STATUS_QUEUED


def test_job_rejects_invalid_status(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, status="invalid"))


def test_job_rejects_empty_kind(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Job(kind=""))


@pytest.mark.parametrize(
    ("attempts", "max_attempts"),
    [
        (-1, 3),
        (4, 3),
        (0, 0),
    ],
)
def test_job_rejects_invalid_attempt_limits(
    database: Database,
    attempts: int,
    max_attempts: int,
) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                Job(
                    kind=JOB_KIND_PROCESS_TRANSCRIPT,
                    attempts=attempts,
                    max_attempts=max_attempts,
                ),
            )


def test_job_rejects_negative_priority(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Job(kind=JOB_KIND_PROCESS_TRANSCRIPT, priority=-1))


def test_job_indexes_exist(database: Database) -> None:
    inspector = inspect(database.engine)
    indexes = {index["name"] for index in inspector.get_indexes("jobs")}

    assert {
        "ix_jobs_queue_claim",
        "ix_jobs_status_updated",
        "ix_jobs_kind_status",
        "ix_jobs_run_id",
        "ix_jobs_status_lease_expires",
        "ix_jobs_created_at",
    }.issubset(indexes)


def test_session_identity_is_unique(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    MemorySession(session_id="pi-session-1"),
                    MemorySession(session_id="pi-session-1"),
                ],
            )


def test_transcript_path_is_unique_per_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add_all(
                [
                    Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl"),
                    Transcript(session=memory_session, path="/tmp/pi/transcript.jsonl"),
                ],
            )


def test_transcript_stores_unresolved_parent_path(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/child.jsonl",
            parent_transcript_path="/tmp/pi/parent.jsonl",
        )
        session.add(transcript)
        session.flush()
        session.refresh(transcript)

        assert transcript.parent_transcript_path == "/tmp/pi/parent.jsonl"
        assert transcript.parent_transcript_id is None
        assert transcript.parent_transcript is None


def test_transcript_parent_relationships_preserve_children_on_parent_delete(database: Database) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        parent = Transcript(session=memory_session, path="/tmp/pi/parent.jsonl")
        child = Transcript(
            session=memory_session,
            path="/tmp/pi/child.jsonl",
            parent_transcript=parent,
            parent_transcript_path="/tmp/pi/parent.jsonl",
        )
        session.add_all([parent, child])
        session.flush()

        assert child.parent_transcript == parent
        assert parent.child_transcripts == [child]

        session.delete(parent)
        session.flush()
        session.refresh(child)

        assert child.parent_transcript_path == "/tmp/pi/parent.jsonl"
        assert child.parent_transcript_id is None
        assert child.parent_transcript is None


def test_transcript_rejects_invalid_parent_transcript_id(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            session.add(memory_session)
            session.flush()
            session.add(
                Transcript(
                    session_id=memory_session.id,
                    path="/tmp/pi/child.jsonl",
                    parent_transcript_path="/tmp/pi/missing-parent.jsonl",
                    parent_transcript_id=12345,
                ),
            )


def test_transcript_parent_id_requires_parent_path(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            memory_session = MemorySession(session_id="pi-session-1")
            parent = Transcript(session=memory_session, path="/tmp/pi/parent.jsonl")
            session.add(parent)
            session.flush()
            session.add(
                Transcript(
                    session=memory_session,
                    path="/tmp/pi/child.jsonl",
                    parent_transcript_id=parent.id,
                ),
            )


def test_transcript_requires_existing_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Transcript(session_id=12345, path="/tmp/pi/transcript.jsonl"))


def test_observation_requires_existing_session(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(Observation(session_id=12345, request_id="request-1"))


def test_transcript_entry_prevents_duplicate_pi_entry_id(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_id="entry-1",
                        entry_type="message",
                        raw_line='{"id":"entry-1"}',
                        byte_start=0,
                        byte_end=16,
                    ),
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_id="entry-1",
                        entry_type="message",
                        raw_line='{"id":"entry-1"}',
                        byte_start=17,
                        byte_end=33,
                    ),
                ],
            )


def test_transcript_entry_prevents_duplicate_byte_span(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add_all(
                [
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_type="message",
                        raw_line='{"type":"message"}',
                        byte_start=0,
                        byte_end=18,
                    ),
                    TranscriptEntry(
                        transcript_id=transcript_id,
                        entry_type="event",
                        raw_line='{"type":"event"}',
                        byte_start=0,
                        byte_end=18,
                    ),
                ],
            )


def test_transcript_entry_requires_positive_byte_span(database: Database) -> None:
    transcript_id = create_transcript(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                TranscriptEntry(
                    transcript_id=transcript_id,
                    entry_type="message",
                    raw_line='{"type":"message"}',
                    byte_start=18,
                    byte_end=18,
                ),
            )


def test_transcript_entry_requires_existing_transcript(database: Database) -> None:
    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(
                TranscriptEntry(
                    transcript_id=12345,
                    entry_type="message",
                    raw_line='{"type":"message"}',
                    byte_start=0,
                    byte_end=18,
                ),
            )
