from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pi_memory.cli.main as cli_module
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pi_memory.db import (
    DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
    DURABLE_MEMORY_SOURCE_KIND_CLAIM,
    DURABLE_MEMORY_STATUS_CANDIDATE,
    DURABLE_MEMORY_STATUS_PROMOTED,
    JOB_KIND_PROMOTE_DURABLE_MEMORY,
    MEMORY_LAYER_LONG_TERM,
    MEMORY_LAYER_SHORT_TERM,
    MEMORY_PROJECTION_COLLECTION_NAME,
    MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
    MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
    MEMORY_PROJECTION_STATUS_INDEXED,
    MEMORY_PROJECTION_STATUS_PENDING,
    SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
    SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
    Database,
    DurableMemoryAuditEvent,
    DurableMemoryItem,
    DurableMemoryRelation,
    DurableMemorySource,
    Job,
    MemoryProjectionRecord,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    Transcript,
)
from pi_memory.durable import DurableMemoryFilterError, DurableMemoryInspectionService
from pi_memory.server import create_app
from sqlalchemy import func, select


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    memory_database = Database(sqlite_url(tmp_path / "memory.db"))
    try:
        memory_database.initialize()
        yield memory_database
    finally:
        memory_database.close_if_open()


@pytest.fixture
def durable_fixture(database: Database) -> dict[str, Any]:
    return create_durable_fixture(database)


@pytest.fixture
def durable_client(database: Database) -> TestClient:
    app = create_app(
        durable_memory_service=DurableMemoryInspectionService(database=database),
    )
    return TestClient(app)


def create_durable_fixture(database: Database) -> dict[str, Any]:
    now = datetime(2026, 2, 3, 4, 5, 6, tzinfo=UTC)
    with database.session() as session:
        job = Job(kind=JOB_KIND_PROMOTE_DURABLE_MEMORY, created_at=now, updated_at=now)
        first_session = MemorySession(
            session_id="pi-session-durable-1",
            cwd="/repo",
            repo_name="basecamp",
            repo_root="/repo",
            worktree_label="wt-memory",
            worktree_path="/worktrees/wt-memory",
            created_at=now,
            updated_at=now,
        )
        second_session = MemorySession(
            session_id="pi-session-durable-2",
            cwd="/repo-other",
            repo_name="other-repo",
            repo_root="/repo-other",
            worktree_label="main",
            worktree_path="/repo-other",
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
        )
        first_transcript = Transcript(session=first_session, path="/tmp/pi/durable-1.jsonl")
        second_transcript = Transcript(session=second_session, path="/tmp/pi/durable-2.jsonl")
        first_snapshot = SessionInterpretationSnapshot(
            session=first_session,
            transcript=first_transcript,
            job=job,
            status="completed",
            interpretation_json={"claims": [{"statement": "Remember durable inspection."}]},
            analyzed_through_byte_offset=100,
            claim_source_activity_count=1,
            created_at=now,
            updated_at=now,
        )
        second_snapshot = SessionInterpretationSnapshot(
            session=second_session,
            transcript=second_transcript,
            status="completed",
            interpretation_json={"claims": [{"statement": "Other durable memory."}]},
            analyzed_through_byte_offset=100,
            claim_source_activity_count=1,
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
        )
        first_report = SessionInterpretationQualityReport(
            snapshot=first_snapshot,
            job=job,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
            semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
            promotable=True,
            claim_assessments_json=[{"claim_index": 0, "promotable": True}],
            created_at=now,
            updated_at=now,
        )
        second_report = SessionInterpretationQualityReport(
            snapshot=second_snapshot,
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            derivation_status=SESSION_INTERPRETATION_DERIVATION_STATUS_CURRENT,
            deterministic_status=SESSION_INTERPRETATION_DETERMINISTIC_STATUS_PASSED,
            semantic_status=SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
            promotable=True,
            claim_assessments_json=[{"claim_index": 0, "promotable": True}],
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
        )
        first_memory = DurableMemoryItem(
            session=first_session,
            transcript=first_transcript,
            snapshot=first_snapshot,
            quality_report=first_report,
            job=job,
            status=DURABLE_MEMORY_STATUS_PROMOTED,
            status_reason="initial_promotion",
            claim_index=0,
            claim_kind="decision",
            statement="Remember durable inspection.",
            confidence=0.92,
            content_hash="durable-hash-1",
            evaluation_json={"score": 0.92},
            relation_summary_json={"novel": True},
            metadata_json={"scope": "repo"},
            created_at=now,
            updated_at=now + timedelta(seconds=2),
        )
        second_memory = DurableMemoryItem(
            session=second_session,
            transcript=second_transcript,
            snapshot=second_snapshot,
            quality_report=second_report,
            status=DURABLE_MEMORY_STATUS_CANDIDATE,
            claim_index=0,
            claim_kind="fact",
            statement="Other durable memory.",
            confidence=0.81,
            content_hash="durable-hash-2",
            evaluation_json={"score": 0.81},
            relation_summary_json={},
            metadata_json={"scope": "repo"},
            created_at=now + timedelta(seconds=1),
            updated_at=now + timedelta(seconds=1),
        )
        session.add_all([first_memory, second_memory])
        session.flush()

        source = DurableMemorySource(
            memory=first_memory,
            snapshot=first_snapshot,
            quality_report=first_report,
            claim_index=0,
            source_ref="claim:0",
            source_kind=DURABLE_MEMORY_SOURCE_KIND_CLAIM,
            source_origin="local",
            metadata_json={"citation": "safe"},
            created_at=now,
            updated_at=now,
        )
        relation = DurableMemoryRelation(
            memory=first_memory,
            related_memory=second_memory,
            relation_type=DURABLE_MEMORY_RELATION_TYPE_REINFORCES,
            similarity_score=0.77,
            confidence=0.8,
            metadata_json={"reason": "similar"},
            created_at=now,
            updated_at=now,
        )
        first_audit = DurableMemoryAuditEvent(
            memory=first_memory,
            job=job,
            event_type="status_transition",
            from_status=DURABLE_MEMORY_STATUS_CANDIDATE,
            to_status=DURABLE_MEMORY_STATUS_PROMOTED,
            reason_code="initial_promotion",
            details_json={"ok": True},
            created_at=now,
        )
        second_audit = DurableMemoryAuditEvent(
            memory=first_memory,
            event_type="metadata_update",
            from_status=DURABLE_MEMORY_STATUS_PROMOTED,
            to_status=DURABLE_MEMORY_STATUS_PROMOTED,
            reason_code="metadata_refresh",
            details_json={"field": "metadata_json"},
            created_at=now + timedelta(seconds=1),
        )
        long_projection = MemoryProjectionRecord(
            collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
            chroma_id="durable-chroma-1",
            record_key="durable:1",
            record_type=MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
            memory_layer=MEMORY_LAYER_LONG_TERM,
            source_table="durable_memory_items",
            source_id=first_memory.id,
            durable_memory=first_memory,
            content_hash="durable-hash-1",
            embedding_model="test-embed",
            embedding_dimension=384,
            status=MEMORY_PROJECTION_STATUS_INDEXED,
            recall_visible=True,
            relation_visible=True,
            metadata_json={"kind": "durable"},
            indexed_at=now,
            created_at=now,
            updated_at=now,
        )
        short_projection = MemoryProjectionRecord(
            collection_name=MEMORY_PROJECTION_COLLECTION_NAME,
            chroma_id="session-chroma-1",
            record_key="session:1:0",
            record_type=MEMORY_PROJECTION_RECORD_TYPE_SESSION_CLAIM,
            memory_layer=MEMORY_LAYER_SHORT_TERM,
            source_table="session_interpretation_snapshots",
            source_id=first_snapshot.id,
            snapshot=first_snapshot,
            quality_report=first_report,
            claim_index=0,
            content_hash="session-hash-1",
            status=MEMORY_PROJECTION_STATUS_PENDING,
            recall_visible=False,
            relation_visible=False,
            metadata_json={"kind": "session"},
            created_at=now,
            updated_at=now,
        )
        session.add_all([source, relation, first_audit, second_audit, long_projection, short_projection])
        session.flush()
        return {
            "memory_id": first_memory.id,
            "related_memory_id": second_memory.id,
            "session_id": first_session.session_id,
            "job_id": job.id,
            "source_id": source.id,
            "relation_id": relation.id,
            "audit_ids": [first_audit.id, second_audit.id],
            "projection_ids": [long_projection.id, short_projection.id],
            "created_at": now,
        }


def table_counts(database: Database) -> dict[str, int]:
    tables = {
        "memories": DurableMemoryItem,
        "sources": DurableMemorySource,
        "relations": DurableMemoryRelation,
        "audit": DurableMemoryAuditEvent,
        "projections": MemoryProjectionRecord,
    }
    with database.session() as session:
        return {
            name: int(session.scalar(select(func.count()).select_from(model)) or 0) for name, model in tables.items()
        }


def test_get_memory_by_id_excludes_audit_by_default(database: Database, durable_fixture: dict[str, Any]) -> None:
    payload = DurableMemoryInspectionService(database=database).get_memory(durable_fixture["memory_id"])

    assert payload is not None
    assert payload["memory_id"] == durable_fixture["memory_id"]
    assert payload["session_id"] == "pi-session-durable-1"
    assert payload["session_metadata"]["repo_name"] == "basecamp"
    assert payload["claim_kind"] == "decision"
    assert payload["evaluation_json"] == {"score": 0.92}
    assert payload["sources"][0]["source_ref"] == "claim:0"
    assert payload["relations_from"][0]["related_memory_id"] == durable_fixture["related_memory_id"]
    assert payload["relations_to"] == []
    assert payload["projection_records"][0]["record_type"] == MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY
    assert "audit_events" not in payload
    assert datetime.fromisoformat(payload["created_at"]) == durable_fixture["created_at"].replace(tzinfo=None)


def test_get_memory_by_id_returns_none_when_missing(database: Database) -> None:
    assert DurableMemoryInspectionService(database=database).get_memory(9999) is None


def test_get_memory_by_id_includes_audit_when_requested(database: Database, durable_fixture: dict[str, Any]) -> None:
    payload = DurableMemoryInspectionService(database=database).get_memory(
        durable_fixture["memory_id"],
        include_audit=True,
    )

    assert payload is not None
    assert [event["event_id"] for event in payload["audit_events"]] == durable_fixture["audit_ids"]
    assert payload["audit_events"][0]["details_json"] == {"ok": True}


def test_list_memories_filters_and_paginates(database: Database, durable_fixture: dict[str, Any]) -> None:
    service = DurableMemoryInspectionService(database=database)

    filtered = service.list_memories(
        status=DURABLE_MEMORY_STATUS_PROMOTED,
        repo_name="basecamp",
        worktree_label="wt-memory",
        session_id="pi-session-durable-1",
        limit=10,
        offset=0,
    ).to_payload()
    paged = service.list_memories(limit=1, offset=1).to_payload()

    assert filtered["pagination"] == {"total": 1, "returned": 1, "limit": 10, "offset": 0}
    assert filtered["query"]["status"] == DURABLE_MEMORY_STATUS_PROMOTED
    assert filtered["results"][0]["memory_id"] == durable_fixture["memory_id"]
    assert paged["pagination"]["total"] == 2
    assert paged["pagination"]["returned"] == 1


def test_audit_returns_none_when_memory_is_missing(database: Database) -> None:
    assert DurableMemoryInspectionService(database=database).list_audit_events(9999) is None


def test_audit_pagination(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = DurableMemoryInspectionService(database=database).list_audit_events(
        durable_fixture["memory_id"],
        limit=1,
        offset=1,
    )

    assert result is not None
    payload = result.to_payload()
    assert payload["pagination"] == {"total": 2, "returned": 1, "limit": 1, "offset": 1}
    assert payload["results"][0]["reason_code"] == "metadata_refresh"


def test_projection_list_filters(database: Database, durable_fixture: dict[str, Any]) -> None:
    payload = (
        DurableMemoryInspectionService(database=database)
        .list_projection_records(
            record_type=MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
            memory_layer=MEMORY_LAYER_LONG_TERM,
            projection_status=MEMORY_PROJECTION_STATUS_INDEXED,
            recall_visible=True,
            relation_visible=True,
        )
        .to_payload()
    )

    assert payload["pagination"]["total"] == 1
    assert payload["results"][0]["projection_record_id"] == durable_fixture["projection_ids"][0]
    assert payload["results"][0]["embedding_model"] == "test-embed"
    assert datetime.fromisoformat(payload["results"][0]["indexed_at"]) == durable_fixture["created_at"].replace(
        tzinfo=None,
    )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"status": "invalid"}, "Invalid status"),
        ({"limit": 0}, "limit must be between 1 and 100"),
        ({"limit": 101}, "limit must be between 1 and 100"),
        ({"offset": -1}, "offset must be non-negative"),
    ],
)
def test_invalid_memory_filters_raise(database: Database, kwargs: dict[str, Any], message: str) -> None:
    service = DurableMemoryInspectionService(database=database)

    with pytest.raises(DurableMemoryFilterError, match=message):
        service.list_memories(**kwargs)


def test_invalid_audit_pagination_raises(database: Database, durable_fixture: dict[str, Any]) -> None:
    service = DurableMemoryInspectionService(database=database)

    with pytest.raises(DurableMemoryFilterError, match="limit must be between 1 and 100"):
        service.list_audit_events(durable_fixture["memory_id"], limit=0)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"record_type": "invalid"}, "Invalid record_type"),
        ({"memory_layer": "invalid"}, "Invalid memory_layer"),
        ({"projection_status": "invalid"}, "Invalid projection_status"),
    ],
)
def test_invalid_projection_filters_raise(
    database: Database,
    kwargs: dict[str, Any],
    message: str,
) -> None:
    service = DurableMemoryInspectionService(database=database)

    with pytest.raises(DurableMemoryFilterError, match=message):
        service.list_projection_records(**kwargs)


def test_service_calls_do_not_mutate_counts(database: Database, durable_fixture: dict[str, Any]) -> None:
    before = table_counts(database)
    service = DurableMemoryInspectionService(database=database)

    service.get_memory(durable_fixture["memory_id"], include_audit=True)
    service.list_memories(status=DURABLE_MEMORY_STATUS_PROMOTED)
    service.list_audit_events(durable_fixture["memory_id"])
    service.list_projection_records(recall_visible=True)

    assert table_counts(database) == before


def test_api_lists_gets_audit_and_projections(
    durable_client: TestClient,
    durable_fixture: dict[str, Any],
) -> None:
    list_response = durable_client.get("/v1/durable-memory", params={"status": DURABLE_MEMORY_STATUS_PROMOTED})
    get_response = durable_client.get(f"/v1/durable-memory/{durable_fixture['memory_id']}")
    audit_response = durable_client.get(f"/v1/durable-memory/{durable_fixture['memory_id']}/audit")
    projection_response = durable_client.get(
        "/v1/memory-projections",
        params={"record_type": MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY},
    )

    assert list_response.status_code == 200
    assert list_response.json()["pagination"]["total"] == 1
    assert get_response.status_code == 200
    assert get_response.json()["memory_id"] == durable_fixture["memory_id"]
    assert "audit_events" not in get_response.json()
    assert audit_response.status_code == 200
    assert audit_response.json()["pagination"]["total"] == 2
    assert projection_response.status_code == 200
    assert projection_response.json()["results"][0]["record_type"] == MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY


def test_api_include_audit_404_and_invalid_filter(
    durable_client: TestClient,
    durable_fixture: dict[str, Any],
) -> None:
    include_response = durable_client.get(
        f"/v1/durable-memory/{durable_fixture['memory_id']}",
        params={"include_audit": True},
    )
    missing_response = durable_client.get("/v1/durable-memory/9999")
    missing_audit_response = durable_client.get("/v1/durable-memory/9999/audit")
    invalid_response = durable_client.get("/v1/durable-memory", params={"status": "invalid"})
    invalid_projection_response = durable_client.get("/v1/memory-projections", params={"record_type": "invalid"})

    assert include_response.status_code == 200
    assert len(include_response.json()["audit_events"]) == 2
    assert missing_response.status_code == 404
    assert missing_audit_response.status_code == 404
    assert invalid_response.status_code == 422
    assert invalid_projection_response.status_code == 422


def test_cli_durable_json(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "durable",
            "--memory-id",
            str(durable_fixture["memory_id"]),
            "--db-url",
            database.url,
            "--include-audit",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["memory_id"] == durable_fixture["memory_id"]
    assert len(payload["audit_events"]) == 2


def test_cli_durable_human_output(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "durable",
            "--memory-id",
            str(durable_fixture["memory_id"]),
            "--db-url",
            database.url,
        ],
    )

    assert result.exit_code == 0
    assert "Durable memory" in result.output
    assert "Remember durable inspection." in result.output


def test_cli_durable_list_filter(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "durable-list",
            "--db-url",
            database.url,
            "--status",
            DURABLE_MEMORY_STATUS_PROMOTED,
            "--repo-name",
            "basecamp",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["pagination"]["total"] == 1
    assert payload["results"][0]["memory_id"] == durable_fixture["memory_id"]


def test_cli_durable_audit(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "durable-audit",
            "--memory-id",
            str(durable_fixture["memory_id"]),
            "--db-url",
            database.url,
            "--limit",
            "1",
            "--offset",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["pagination"]["returned"] == 1
    assert payload["results"][0]["reason_code"] == "metadata_refresh"


def test_cli_projection_list(database: Database, durable_fixture: dict[str, Any]) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        [
            "projection-list",
            "--db-url",
            database.url,
            "--record-type",
            MEMORY_PROJECTION_RECORD_TYPE_DURABLE_MEMORY,
            "--layer",
            MEMORY_LAYER_LONG_TERM,
            "--status",
            MEMORY_PROJECTION_STATUS_INDEXED,
            "--recall-visible",
            "--relation-visible",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["pagination"]["total"] == 1
    assert payload["results"][0]["projection_record_id"] == durable_fixture["projection_ids"][0]


def test_cli_projection_invalid_filter_exits_nonzero(database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["projection-list", "--db-url", database.url, "--record-type", "invalid", "--json"],
    )

    assert result.exit_code != 0
    assert "Invalid record_type: invalid" in result.output


def test_cli_invalid_filter_exits_nonzero(database: Database) -> None:
    result = CliRunner().invoke(
        cli_module.main,
        ["durable-list", "--db-url", database.url, "--status", "invalid", "--json"],
    )

    assert result.exit_code != 0
    assert "Invalid status: invalid" in result.output
