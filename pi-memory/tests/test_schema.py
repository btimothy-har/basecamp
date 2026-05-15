from pathlib import Path

import pytest
from pi_memory.db import (
    ACTIVITY_KIND_USER_TEXT,
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_RUNNING,
    EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    EPISODE_STATUS_CLOSED,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_QUEUED,
    SESSION_SNAPSHOT_STATUS_READY_FOR_INTERPRETATION,
    ActivityUnit,
    AnalysisRun,
    Database,
    Episode,
    EpisodeManifest,
    Job,
    MemorySession,
    Observation,
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
        "session_snapshot_shells",
    }.issubset(table_names)


def test_initialize_does_not_create_future_memory_tables(database: Database) -> None:
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


def test_analysis_run_rejects_invalid_status(database: Database) -> None:
    session_id, transcript_id, _ = create_analysis_run(database)

    with pytest.raises(IntegrityError):
        with database.session() as session:
            session.add(AnalysisRun(session_id=session_id, transcript_id=transcript_id, status="invalid"))


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
        assert manifest.omitted_raw_text_bytes == 0
        assert manifest.created_at is not None
        assert manifest.updated_at is not None


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
            omitted_raw_text_bytes=10**12,
        )
        session.add_all([activity_unit, manifest])
        session.flush()
        session.refresh(activity_unit)
        session.refresh(manifest)

        assert activity_unit.result_text_byte_count == 10**12
        assert activity_unit.result_text_line_count == 10**9
        assert manifest.source_spans_json == [{"entry_id": 1, "raw_text_bytes": 10**12}]
        assert manifest.omitted_raw_text_bytes == 10**12


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
