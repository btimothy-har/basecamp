from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.db import (
    ANALYSIS_STATUS_COMPLETED,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE,
    SESSION_INTERPRETATION_STATUS_BLOCKED,
    SESSION_INTERPRETATION_STATUS_COMPLETED,
    SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
    SOURCE_ORIGIN_INHERITED,
    SOURCE_ORIGIN_LOCAL,
    SOURCE_ORIGIN_MIXED,
    SOURCE_ORIGIN_UNKNOWN,
    ActivityUnit,
    AnalysisRun,
    Database,
    Episode,
    EpisodeManifest,
    Job,
    MemorySession,
    SessionInterpretationSnapshot,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation import (
    INTERPRETATION_PROMPT_VERSION,
    INTERPRETATION_SCHEMA_VERSION,
    DeterministicSessionInterpreter,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
)
from pi_memory.interpretation.packets import InterpretationPacket
from pi_memory.jobs import (
    InvalidJobPayloadError,
    JobRunner,
    JobRunTokenMismatchError,
    JobStore,
    TranscriptNotFoundError,
    UnsupportedJobKindError,
)
from sqlalchemy import func, select, text


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


@pytest.fixture
def store(database: Database) -> JobStore:
    return JobStore(database=database)


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 1, 1, hour, minute, tzinfo=UTC)


class RecordingInterpreter:
    def __init__(self) -> None:
        self.calls: list[InterpretationPacket] = []

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        self.calls.append(packet)
        return DeterministicSessionInterpreter().interpret(packet)


class FailingInterpreter:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error if error is not None else AssertionError("interpreter should not be called")

    def interpret(self, _packet: InterpretationPacket) -> InterpretationResult:
        self.calls += 1
        raise self.error


def create_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/transcript.jsonl",
            cursor_offset=200,
            file_size=250,
        )
        session.add(transcript)
        session.flush()
        session.add_all(
            [
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id="entry-1",
                    entry_type="message",
                    message_role="user",
                    raw_line=(
                        '{"type":"message","message":{"role":"user",'
                        '"content":[{"type":"text","text":"find nebula notes"}]}}'
                    ),
                    byte_start=0,
                    byte_end=100,
                ),
                TranscriptEntry(
                    transcript_id=transcript.id,
                    entry_id="entry-2",
                    entry_type="message",
                    message_role="assistant",
                    raw_line='{"secret":"do not expose two"}',
                    byte_start=100,
                    byte_end=200,
                ),
            ],
        )
        session.flush()
        return transcript.id


def create_empty_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-empty")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/pi/empty-transcript.jsonl",
            cursor_offset=0,
            file_size=0,
        )
        session.add(transcript)
        session.flush()
        return transcript.id


def raw_event(entry_type: str, **extra: object) -> str:
    return json.dumps({"type": entry_type, **extra}, separators=(",", ":"))


def raw_message(role: str, content: object, **extra: object) -> str:
    return json.dumps(
        {"type": "message", "message": {"role": role, "content": content, **extra}},
        separators=(",", ":"),
    )


def add_transcript_entry(
    session,
    *,
    transcript_id: int,
    entry_id: str | None,
    entry_type: str,
    raw_line: str,
    byte_start: int,
    message_role: str | None = None,
) -> TranscriptEntry:
    entry = TranscriptEntry(
        transcript_id=transcript_id,
        entry_id=entry_id,
        entry_type=entry_type,
        message_role=message_role,
        raw_line=raw_line,
        byte_start=byte_start,
        byte_end=byte_start + len(raw_line.encode("utf-8")),
    )
    session.add(entry)
    return entry


def create_resolved_fork_child_transcript(database: Database) -> int:
    with database.session() as session:
        parent_session = MemorySession(session_id="pi-parent-session")
        child_session = MemorySession(session_id="pi-child-session")
        parent = Transcript(session=parent_session, path="/tmp/pi/parent.jsonl")
        child = Transcript(
            session=child_session,
            path="/tmp/pi/child.jsonl",
            parent_transcript_path="/tmp/pi/parent.jsonl",
        )
        session.add_all([parent, child])
        session.flush()
        add_transcript_entry(
            session,
            transcript_id=parent.id,
            entry_id="parent-user",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "copied parent prompt"),
            byte_start=0,
        )
        add_transcript_entry(
            session,
            transcript_id=parent.id,
            entry_id="parent-call",
            entry_type="message",
            message_role="assistant",
            raw_line=raw_message(
                "assistant",
                [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"cmd": "pwd"}}],
            ),
            byte_start=100,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="child-session",
            entry_type="session",
            raw_line=raw_event("session", cwd="/workspace"),
            byte_start=0,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="parent-user",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "copied parent prompt"),
            byte_start=100,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="parent-call",
            entry_type="message",
            message_role="assistant",
            raw_line=raw_message(
                "assistant",
                [{"type": "toolCall", "id": "call-1", "name": "bash", "arguments": {"cmd": "pwd"}}],
            ),
            byte_start=200,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="child-result",
            entry_type="message",
            message_role="toolResult",
            raw_line=raw_message("toolResult", "ok", toolCallId="call-1", isError=False),
            byte_start=300,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="child-user",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "new child prompt"),
            byte_start=400,
        )
        session.flush()
        return child.id


def create_unresolved_fork_child_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-unresolved")
        child = Transcript(
            session=memory_session,
            path="/tmp/pi/unresolved-child.jsonl",
            parent_transcript_path="/tmp/pi/missing-parent.jsonl",
        )
        session.add(child)
        session.flush()
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="child-session",
            entry_type="session",
            raw_line=raw_event("session", cwd="/workspace"),
            byte_start=0,
        )
        add_transcript_entry(
            session,
            transcript_id=child.id,
            entry_id="unknown-user",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "copied or new is unknown"),
            byte_start=100,
        )
        session.flush()
        return child.id


def create_compaction_boundary_transcript(database: Database) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-compaction")
        transcript = Transcript(session=memory_session, path="/tmp/pi/compaction.jsonl")
        session.add(transcript)
        session.flush()
        add_transcript_entry(
            session,
            transcript_id=transcript.id,
            entry_id="before",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "before compaction"),
            byte_start=0,
        )
        add_transcript_entry(
            session,
            transcript_id=transcript.id,
            entry_id="compact",
            entry_type="compaction",
            raw_line=raw_event("compaction", summary="compacted earlier context"),
            byte_start=100,
        )
        add_transcript_entry(
            session,
            transcript_id=transcript.id,
            entry_id="after",
            entry_type="message",
            message_role="user",
            raw_line=raw_message("user", "after compaction"),
            byte_start=200,
        )
        session.flush()
        return transcript.id


def claim_process_transcript_job(store: JobStore, transcript_id: int | None = None, payload_json=None) -> Job:
    if payload_json is None:
        payload_json = {"transcript_id": transcript_id}
    store.enqueue(JOB_KIND_PROCESS_TRANSCRIPT, payload_json=payload_json, due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None
    return claimed


def claim_interpret_session_job(store: JobStore, transcript_id: int | None = None, payload_json=None) -> Job:
    if payload_json is None:
        payload_json = {"transcript_id": transcript_id}
    store.enqueue(JOB_KIND_INTERPRET_SESSION, payload_json=payload_json, due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None
    return claimed


def process_transcript(database: Database, store: JobStore, transcript_id: int) -> Job:
    claimed = claim_process_transcript_job(store, transcript_id)
    return JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))


def get_job(database: Database, job_id: int) -> Job:
    with database.session() as session:
        return session.get_one(Job, job_id)


UNSET = object()


def assert_phase_5a_result(
    phase_5a: dict[str, object],
    *,
    activity_count: int,
    episode_count: int,
    manifest_count: int,
    analyzed_through_byte_offset: int,
    analyzed_through_entry_id: int | None | object = UNSET,
) -> None:
    assert isinstance(phase_5a["analysis_run_id"], int)
    assert phase_5a["status"] == ANALYSIS_STATUS_COMPLETED
    assert phase_5a["activity_count"] == activity_count
    assert phase_5a["episode_count"] == episode_count
    assert phase_5a["manifest_count"] == manifest_count
    assert isinstance(phase_5a["snapshot_shell_id"], int)
    if analyzed_through_entry_id is UNSET:
        assert isinstance(phase_5a["analyzed_through_entry_id"], int)
    else:
        assert phase_5a["analyzed_through_entry_id"] == analyzed_through_entry_id
    assert phase_5a["analyzed_through_byte_offset"] == analyzed_through_byte_offset


def test_process_transcript_completes_and_writes_safe_result(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.attempts == 1
    assert completed.exit_code == 0
    assert completed.result_json is not None
    phase_5a = completed.result_json["phase_5a"]
    assert isinstance(phase_5a, dict)
    interpret_session_job_id = completed.result_json["interpret_session_job_id"]
    assert isinstance(interpret_session_job_id, int)
    base_result = {
        key: value
        for key, value in completed.result_json.items()
        if key not in {"phase_5a", "interpret_session_job_id"}
    }
    assert base_result == {
        "transcript_id": transcript_id,
        "session_id": "pi-session-1",
        "entry_count": 2,
        "cursor_offset": 200,
        "file_size": 250,
        "indexed_entry_count": 1,
    }
    assert_phase_5a_result(
        phase_5a,
        activity_count=2,
        episode_count=1,
        manifest_count=1,
        analyzed_through_byte_offset=200,
    )
    assert "do not expose" not in str(completed.result_json)
    assert "find nebula notes" not in str(completed.result_json)

    with database.session() as session:
        interpret_job = session.get_one(Job, interpret_session_job_id)
        assert interpret_job.kind == JOB_KIND_INTERPRET_SESSION
        assert interpret_job.status == JOB_STATUS_QUEUED
        assert interpret_job.payload_json == {
            "transcript_id": transcript_id,
            "analysis_run_id": phase_5a["analysis_run_id"],
            "session_id": "pi-session-1",
            "process_job_id": claimed.id,
            "analyzed_through_entry_id": phase_5a["analyzed_through_entry_id"],
            "analyzed_through_byte_offset": 200,
            "activity_count": 2,
            "episode_count": 1,
            "manifest_count": 1,
        }
        assert "raw_line" not in interpret_job.payload_json

    with database.engine.connect() as connection:
        matches = (
            connection.execute(
                text("SELECT rowid FROM transcript_entries_fts WHERE transcript_entries_fts MATCH :query"),
                {"query": "nebula"},
            )
            .scalars()
            .all()
        )

    assert len(matches) == 1


def test_process_transcript_enqueued_interpret_job_writes_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    interpret_session_job_id = process.result_json["interpret_session_job_id"]

    claimed = store.claim_next("worker-interpret")
    assert claimed is not None
    assert claimed.id == interpret_session_job_id
    completed = JobRunner(database=database).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_COMPLETED
    assert completed.result_json["analysis_run_id"] == process.result_json["phase_5a"]["analysis_run_id"]
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.job_id == interpret_session_job_id
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED


def test_process_transcript_handles_empty_transcript(database: Database, store: JobStore) -> None:
    transcript_id = create_empty_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.result_json is not None
    phase_5a = completed.result_json["phase_5a"]
    assert isinstance(phase_5a, dict)
    assert completed.result_json["entry_count"] == 0
    assert completed.result_json["indexed_entry_count"] == 0
    assert_phase_5a_result(
        phase_5a,
        activity_count=0,
        episode_count=0,
        manifest_count=0,
        analyzed_through_entry_id=None,
        analyzed_through_byte_offset=0,
    )
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(ActivityUnit)) == 0
        assert session.scalar(select(func.count()).select_from(Episode)) == 0
        assert session.scalar(select(func.count()).select_from(EpisodeManifest)) == 0
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 1
        shell = session.scalar(select(SessionSnapshotShell))
        assert shell is not None
        assert shell.analyzed_through_entry_id is None
        assert shell.analyzed_through_byte_offset == 0


def test_process_transcript_persists_phase_5a_rows(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))
    assert completed.result_json is not None
    phase_5a = completed.result_json["phase_5a"]
    assert isinstance(phase_5a, dict)

    with database.session() as session:
        analysis_run = session.scalar(select(AnalysisRun).where(AnalysisRun.transcript_id == transcript_id))
        assert analysis_run is not None
        assert analysis_run.id == phase_5a["analysis_run_id"]
        assert analysis_run.job_id == claimed.id
        assert analysis_run.status == ANALYSIS_STATUS_COMPLETED
        assert analysis_run.source_byte_start == 0
        assert analysis_run.source_byte_end == 200
        assert analysis_run.activity_count == 2
        assert analysis_run.episode_count == 1
        assert analysis_run.manifest_count == 1
        assert analysis_run.diagnostics_json == {
            "phase": "5A",
            "analysis_kind": "transcript_structure",
            "entry_count": 2,
        }

        assert session.scalar(select(func.count()).select_from(ActivityUnit)) == 2
        assert session.scalar(select(func.count()).select_from(Episode)) == 1
        assert session.scalar(select(func.count()).select_from(EpisodeManifest)) == 1
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 1

        entry_ids = list(
            session.scalars(
                select(TranscriptEntry.id)
                .where(TranscriptEntry.transcript_id == transcript_id)
                .order_by(TranscriptEntry.byte_start),
            ),
        )
        assert phase_5a["analyzed_through_entry_id"] == entry_ids[-1]
        activities = list(session.scalars(select(ActivityUnit).order_by(ActivityUnit.ordinal)))
        assert all(activity.episode_id is not None for activity in activities)
        assert [activity.source_entry_ids_json for activity in activities] == [[entry_ids[0]], [entry_ids[1]]]

        episode = session.scalar(select(Episode))
        assert episode is not None
        assert episode.activity_count == 2
        assert episode.byte_start == 0
        assert episode.byte_end == 200

        manifest = session.scalar(select(EpisodeManifest))
        assert manifest is not None
        assert manifest.episode_id == episode.id
        assert manifest.activity_map_json["kind"] == "episode_manifest_activity_map"
        assert manifest.source_spans_json[0] == {
            "kind": "episode",
            "episode_ordinal": 0,
            "byte_start": 0,
            "byte_end": 200,
            "first_entry_id": episode.first_entry_id,
            "last_entry_id": episode.last_entry_id,
            "timestamp_start": None,
            "timestamp_end": None,
        }

        shell = session.scalar(select(SessionSnapshotShell))
        assert shell is not None
        assert shell.id == phase_5a["snapshot_shell_id"]
        assert shell.analysis_run_id == analysis_run.id
        assert shell.transcript_id == transcript_id
        assert shell.activity_count == 2
        assert shell.episode_count == 1
        assert shell.manifest_count == 1
        assert shell.analyzed_through_byte_offset == 200
        assert shell.snapshot_json["kind"] == "session_snapshot_shell"
        assert shell.snapshot_json["counts"] == {
            "activity_count": 2,
            "episode_count": 1,
            "manifest_count": 1,
            "tool_pair_count": 0,
            "local_activity_count": 2,
            "inherited_activity_count": 0,
            "mixed_activity_count": 0,
            "unknown_activity_count": 0,
            "claim_source_activity_count": 2,
        }


def test_process_transcript_persists_resolved_fork_source_origins(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_resolved_fork_child_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    with database.session() as session:
        transcript = session.get_one(Transcript, transcript_id)
        assert transcript.parent_transcript_id is not None
        assert transcript.parent_transcript is not None
        assert transcript.session_id != transcript.parent_transcript.session_id

        activities = list(session.scalars(select(ActivityUnit).order_by(ActivityUnit.ordinal)))
        assert [activity.source_origin for activity in activities] == [
            SOURCE_ORIGIN_LOCAL,
            SOURCE_ORIGIN_INHERITED,
            SOURCE_ORIGIN_MIXED,
            SOURCE_ORIGIN_LOCAL,
        ]
        assert activities[0].kind == "session_event"
        assert activities[0].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_LOCAL: activities[0].source_entry_ids_json,
        }
        assert activities[1].kind == "user_text"
        assert activities[1].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_INHERITED: activities[1].source_entry_ids_json,
        }
        assert activities[2].kind == "tool_pair"
        assert activities[2].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_INHERITED: [activities[2].source_entry_ids_json[0]],
            SOURCE_ORIGIN_LOCAL: [activities[2].source_entry_ids_json[1]],
        }
        assert activities[3].kind == "user_text"
        assert activities[3].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_LOCAL: activities[3].source_entry_ids_json,
        }

        shell = session.scalar(select(SessionSnapshotShell))
        assert shell is not None
        assert shell.snapshot_json["ready_for_interpretation"] is True
        assert shell.snapshot_json["fork"] == {
            "has_parent": True,
            "parent_transcript_path": "/tmp/pi/parent.jsonl",
            "parent_transcript_id": transcript.parent_transcript_id,
            "parent_resolved": True,
            "source_origin_complete": True,
            "blocked_reason": None,
        }
        assert shell.snapshot_json["counts"] == {
            "activity_count": 4,
            "episode_count": 1,
            "manifest_count": 1,
            "tool_pair_count": 1,
            "local_activity_count": 2,
            "inherited_activity_count": 1,
            "mixed_activity_count": 1,
            "unknown_activity_count": 0,
            "claim_source_activity_count": 2,
        }

        manifest = session.scalar(select(EpisodeManifest))
        assert manifest is not None
        manifest_activities = manifest.activity_map_json["activities"]
        assert [item["source_origin"] for item in manifest_activities] == [
            SOURCE_ORIGIN_LOCAL,
            SOURCE_ORIGIN_INHERITED,
            SOURCE_ORIGIN_MIXED,
            SOURCE_ORIGIN_LOCAL,
        ]
        assert [item["claim_source_allowed"] for item in manifest_activities] == [
            False,
            False,
            True,
            True,
        ]
        assert manifest.activity_map_json["origin_counts"] == {
            "local_activity_count": 2,
            "inherited_activity_count": 1,
            "mixed_activity_count": 1,
            "unknown_activity_count": 0,
        }
        assert manifest.activity_map_json["claim_source_activity_count"] == 2


def test_process_transcript_persists_unresolved_fork_source_origins(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_unresolved_fork_child_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    with database.session() as session:
        transcript = session.get_one(Transcript, transcript_id)
        assert transcript.parent_transcript_path == "/tmp/pi/missing-parent.jsonl"
        assert transcript.parent_transcript_id is None

        activities = list(session.scalars(select(ActivityUnit).order_by(ActivityUnit.ordinal)))
        assert [activity.kind for activity in activities] == ["session_event", "user_text"]
        assert [activity.source_origin for activity in activities] == [SOURCE_ORIGIN_LOCAL, SOURCE_ORIGIN_UNKNOWN]
        assert activities[0].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_LOCAL: activities[0].source_entry_ids_json,
        }
        assert activities[1].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_UNKNOWN: activities[1].source_entry_ids_json,
        }

        shell = session.scalar(select(SessionSnapshotShell))
        assert shell is not None
        assert shell.snapshot_json["ready_for_interpretation"] is False
        assert shell.snapshot_json["fork"] == {
            "has_parent": True,
            "parent_transcript_path": "/tmp/pi/missing-parent.jsonl",
            "parent_transcript_id": None,
            "parent_resolved": False,
            "source_origin_complete": False,
            "blocked_reason": "parent_transcript_not_ingested",
        }
        assert shell.snapshot_json["counts"] == {
            "activity_count": 2,
            "episode_count": 1,
            "manifest_count": 1,
            "tool_pair_count": 0,
            "local_activity_count": 1,
            "inherited_activity_count": 0,
            "mixed_activity_count": 0,
            "unknown_activity_count": 1,
            "claim_source_activity_count": 0,
        }


def test_process_transcript_assigns_activity_units_to_compaction_boundary_episodes(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_compaction_boundary_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    with database.session() as session:
        episodes = list(session.scalars(select(Episode).order_by(Episode.ordinal)))
        activities = list(session.scalars(select(ActivityUnit).order_by(ActivityUnit.ordinal)))

        assert [episode.activity_count for episode in episodes] == [2, 1]
        assert [activity.kind for activity in activities] == ["user_text", "compaction", "user_text"]
        assert [activity.episode_id for activity in activities] == [
            episodes[0].id,
            episodes[0].id,
            episodes[1].id,
        ]


def test_process_transcript_phase_5a_rerun_replaces_derived_rows(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    first_claimed = claim_process_transcript_job(store, transcript_id)
    first_completed = JobRunner(database=database).run(
        first_claimed.id,
        first_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None
    first_phase_5a = first_completed.result_json["phase_5a"]
    assert isinstance(first_phase_5a, dict)
    first_interpret_job_id = first_completed.result_json["interpret_session_job_id"]
    assert isinstance(first_interpret_job_id, int)

    second_claimed = claim_process_transcript_job(store, transcript_id)
    second_completed = JobRunner(database=database).run(
        second_claimed.id,
        second_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert second_completed.result_json is not None
    second_phase_5a = second_completed.result_json["phase_5a"]
    assert isinstance(second_phase_5a, dict)
    second_interpret_job_id = second_completed.result_json["interpret_session_job_id"]
    assert isinstance(second_interpret_job_id, int)
    assert second_interpret_job_id != first_interpret_job_id

    assert_phase_5a_result(
        second_phase_5a,
        activity_count=2,
        episode_count=1,
        manifest_count=1,
        analyzed_through_byte_offset=200,
    )
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 1
        assert session.scalar(select(func.count()).select_from(ActivityUnit)) == 2
        assert session.scalar(select(func.count()).select_from(Episode)) == 1
        assert session.scalar(select(func.count()).select_from(EpisodeManifest)) == 1
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 1
        analysis_run = session.scalar(select(AnalysisRun))
        assert analysis_run is not None
        assert analysis_run.id == second_phase_5a["analysis_run_id"]
        assert analysis_run.job_id == second_claimed.id
        first_interpret_job = session.get_one(Job, first_interpret_job_id)
        second_interpret_job = session.get_one(Job, second_interpret_job_id)
        assert first_interpret_job.kind == JOB_KIND_INTERPRET_SESSION
        assert second_interpret_job.kind == JOB_KIND_INTERPRET_SESSION
        assert first_interpret_job.payload_json["analysis_run_id"] == first_phase_5a["analysis_run_id"]
        assert first_interpret_job.payload_json["process_job_id"] == first_claimed.id
        assert second_interpret_job.payload_json["analysis_run_id"] == second_phase_5a["analysis_run_id"]
        assert second_interpret_job.payload_json["process_job_id"] == second_claimed.id

    stale_claimed = store.claim_next("worker-interpret")
    assert stale_claimed is not None
    assert stale_claimed.id == first_interpret_job_id
    stale_completed = JobRunner(database=database, interpreter=FailingInterpreter()).run(
        stale_claimed.id,
        stale_claimed.run_id,
        running_pid=123,
    )
    assert stale_completed.result_json is not None
    assert stale_completed.result_json["status"] == "stale"
    assert stale_completed.result_json["is_stale"] is True
    assert stale_completed.result_json["snapshot_id"] is None
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionInterpretationSnapshot)) == 0

    with database.engine.connect() as connection:
        matches = (
            connection.execute(
                text("SELECT rowid FROM transcript_entries_fts WHERE transcript_entries_fts MATCH :query"),
                {"query": "nebula"},
            )
            .scalars()
            .all()
        )
    assert len(matches) == 1


def test_interpret_session_completed_writes_snapshot_and_safe_result(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    interpreter = RecordingInterpreter()
    claimed = claim_interpret_session_job(
        store,
        payload_json={"transcript_id": transcript_id, "analysis_run_id": None},
    )

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert len(interpreter.calls) == 1
    assert completed.result_json is not None
    assert interpreter.calls[0].readiness.transcript_id == transcript_id
    assert interpreter.calls[0].readiness.latest_analysis_run_id == completed.result_json["analysis_run_id"]
    assert len(interpreter.calls[0].episode_packets) == 1
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_COMPLETED
    assert completed.result_json["transcript_id"] == transcript_id
    assert completed.result_json["session_id"] == "pi-session-1"
    assert completed.result_json["claim_source_activity_count"] == 2
    assert completed.result_json["is_stale"] is False
    assert completed.result_json["prompt_version"] == INTERPRETATION_PROMPT_VERSION
    assert completed.result_json["schema_version"] == INTERPRETATION_SCHEMA_VERSION
    assert completed.result_json["model_metadata"] == {
        "provider": "pi-memory",
        "model": "deterministic-session-interpreter-v1",
        "mode": "deterministic",
    }
    assert "interpretation_json" not in completed.result_json
    assert "citations_json" not in completed.result_json
    assert "do not expose" not in str(completed.result_json)
    assert "find nebula notes" not in str(completed.result_json)

    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.id == completed.result_json["snapshot_id"]
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED
        assert snapshot.blocked_reason is None
        assert snapshot.job_id == claimed.id
        assert snapshot.transcript_id == transcript_id
        assert snapshot.analysis_run_id == completed.result_json["analysis_run_id"]
        assert snapshot.interpretation_json["summary"].startswith("Deterministic interpretation")
        assert snapshot.citations_json
        assert snapshot.model_metadata_json["provider"] == "pi-memory"


def test_interpret_session_blocks_without_phase_5a_and_does_not_call_interpreter(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    interpreter = FailingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_BLOCKED
    assert completed.result_json["blocked_reason"] == SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_BLOCKED
        assert snapshot.blocked_reason == SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY
        assert snapshot.interpretation_json == {}
        assert snapshot.citations_json == []
        assert snapshot.model_metadata_json == {}
        assert snapshot.analysis_run_id is None


def test_interpret_session_replaces_blocked_snapshot_after_phase_5a_becomes_ready(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    blocked_claimed = claim_interpret_session_job(store, transcript_id)
    blocked = JobRunner(database=database).run(
        blocked_claimed.id,
        blocked_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert blocked.result_json is not None
    assert blocked.result_json["snapshot_id"] is not None

    process_transcript(database, store, transcript_id)
    completed_claimed = claim_interpret_session_job(store, transcript_id)
    completed = JobRunner(database=database).run(
        completed_claimed.id,
        completed_claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_COMPLETED
    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == completed.result_json["snapshot_id"]
        assert snapshots[0].job_id == completed_claimed.id
        assert snapshots[0].job_id != blocked_claimed.id
        assert snapshots[0].status == SESSION_INTERPRETATION_STATUS_COMPLETED


def test_interpret_session_blocks_unresolved_parent_and_does_not_call_interpreter(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_unresolved_fork_child_transcript(database)
    process_transcript(database, store, transcript_id)
    interpreter = FailingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_BLOCKED
    assert completed.result_json["blocked_reason"] == (
        SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED
    )
    assert completed.result_json["origin_counts"]["unknown_activity_count"] == 1
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_BLOCKED
        assert snapshot.blocked_reason == SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED
        assert snapshot.claim_source_activity_count == 0


def test_interpret_session_blocks_source_origin_incomplete_and_does_not_call_interpreter(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    with database.session() as session:
        activity = session.scalar(select(ActivityUnit).where(ActivityUnit.transcript_id == transcript_id))
        assert activity is not None
        activity.source_origin = SOURCE_ORIGIN_UNKNOWN
    interpreter = FailingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_BLOCKED
    assert completed.result_json["blocked_reason"] == SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE
    assert completed.result_json["origin_counts"]["unknown_activity_count"] == 1
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_BLOCKED
        assert snapshot.blocked_reason == SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE
        assert snapshot.origin_counts_json["unknown_activity_count"] == 1


def test_interpret_session_skips_no_claim_sources_and_does_not_call_interpreter(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_empty_transcript(database)
    process_transcript(database, store, transcript_id)
    interpreter = FailingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES
    assert completed.result_json["blocked_reason"] is None
    assert completed.result_json["claim_source_activity_count"] == 0
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES
        assert snapshot.blocked_reason is None
        assert snapshot.interpretation_json == {}
        assert snapshot.citations_json == []
        assert snapshot.model_metadata_json == {}


def test_interpret_session_replaces_skipped_snapshot_after_claim_source_arrives(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_empty_transcript(database)
    process_transcript(database, store, transcript_id)
    skipped_claimed = claim_interpret_session_job(store, transcript_id)
    skipped = JobRunner(database=database).run(
        skipped_claimed.id,
        skipped_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert skipped.result_json is not None
    assert skipped.result_json["status"] == SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES
    assert skipped.result_json["snapshot_id"] is not None

    with database.session() as session:
        transcript = session.get_one(Transcript, transcript_id)
        raw_line = raw_message("user", "new claim source")
        entry = TranscriptEntry(
            transcript_id=transcript_id,
            entry_id="entry-after-skip",
            entry_type="message",
            message_role="user",
            raw_line=raw_line,
            byte_start=0,
            byte_end=len(raw_line.encode("utf-8")),
        )
        session.add(entry)
        transcript.cursor_offset = entry.byte_end
        transcript.file_size = entry.byte_end

    process_transcript(database, store, transcript_id)
    completed_claimed = claim_interpret_session_job(store, transcript_id)
    completed = JobRunner(database=database).run(
        completed_claimed.id,
        completed_claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_COMPLETED
    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == completed.result_json["snapshot_id"]
        assert snapshots[0].job_id == completed_claimed.id
        assert snapshots[0].job_id != skipped_claimed.id
        assert snapshots[0].status == SESSION_INTERPRETATION_STATUS_COMPLETED


def test_interpret_session_stale_requested_analysis_noops_without_prior_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    analysis_run_id = process.result_json["phase_5a"]["analysis_run_id"]
    interpreter = FailingInterpreter()
    stale_claimed = claim_interpret_session_job(
        store,
        payload_json={"transcript_id": transcript_id, "analysis_run_id": analysis_run_id + 1},
    )

    stale_completed = JobRunner(database=database, interpreter=interpreter).run(
        stale_claimed.id,
        stale_claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert stale_completed.result_json is not None
    assert stale_completed.result_json["status"] == "stale"
    assert stale_completed.result_json["snapshot_id"] is None
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionInterpretationSnapshot)) == 0


def test_interpret_session_stale_requested_analysis_noops_without_replacing_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    first_process = process_transcript(database, store, transcript_id)
    assert first_process.result_json is not None
    old_analysis_run_id = first_process.result_json["phase_5a"]["analysis_run_id"]
    first_interpret = claim_interpret_session_job(store, transcript_id)
    first_completed = JobRunner(database=database).run(
        first_interpret.id,
        first_interpret.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None
    original_snapshot_id = first_completed.result_json["snapshot_id"]

    stale_analysis_run_id = old_analysis_run_id + 1
    interpreter = FailingInterpreter()
    stale_claimed = claim_interpret_session_job(
        store,
        payload_json={"transcript_id": transcript_id, "analysis_run_id": stale_analysis_run_id},
    )

    stale_completed = JobRunner(database=database, interpreter=interpreter).run(
        stale_claimed.id,
        stale_claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert interpreter.calls == 0
    assert stale_completed.result_json is not None
    assert stale_completed.result_json["status"] == "stale"
    assert stale_completed.result_json["snapshot_id"] is None
    assert stale_completed.result_json["analysis_run_id"] == old_analysis_run_id
    assert stale_completed.result_json["requested_analysis_run_id"] == stale_analysis_run_id
    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == original_snapshot_id
        assert snapshots[0].job_id == first_interpret.id


def test_interpret_session_replaces_prior_completed_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    first_claimed = claim_interpret_session_job(store, transcript_id)
    first_completed = JobRunner(database=database).run(
        first_claimed.id,
        first_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None

    second_claimed = claim_interpret_session_job(store, transcript_id)
    second_completed = JobRunner(database=database).run(
        second_claimed.id,
        second_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert second_completed.result_json is not None

    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == second_completed.result_json["snapshot_id"]
        assert snapshots[0].job_id == second_claimed.id
        assert snapshots[0].status == SESSION_INTERPRETATION_STATUS_COMPLETED


def test_interpret_session_validation_failure_terminal_fails_and_preserves_prior_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    first_claimed = claim_interpret_session_job(store, transcript_id)
    first_completed = JobRunner(database=database).run(
        first_claimed.id,
        first_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None
    original_snapshot_id = first_completed.result_json["snapshot_id"]
    bad_interpreter = FailingInterpreter(InterpreterUnavailableError.no_claim_sources())
    failed_claimed = claim_interpret_session_job(store, transcript_id)

    with pytest.raises(InterpreterUnavailableError):
        JobRunner(database=database, interpreter=bad_interpreter).run(
            failed_claimed.id,
            failed_claimed.run_id,
            running_pid=123,
            now=at(10),
        )

    failed_job = get_job(database, failed_claimed.id)
    assert failed_job.status == JOB_STATUS_FAILED
    assert failed_job.attempts == 1
    assert failed_job.last_error == "Interpretation packet has no local or mixed claim-source references"
    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == original_snapshot_id
        assert snapshots[0].job_id == first_claimed.id


def test_interpret_session_validation_error_terminal_fails_and_preserves_prior_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    first_claimed = claim_interpret_session_job(store, transcript_id)
    first_completed = JobRunner(database=database).run(
        first_claimed.id,
        first_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None
    original_snapshot_id = first_completed.result_json["snapshot_id"]
    bad_interpreter = FailingInterpreter(InterpretationValidationError.schema_error())
    failed_claimed = claim_interpret_session_job(store, transcript_id)

    with pytest.raises(InterpretationValidationError):
        JobRunner(database=database, interpreter=bad_interpreter).run(
            failed_claimed.id,
            failed_claimed.run_id,
            running_pid=123,
            now=at(10),
        )

    failed_job = get_job(database, failed_claimed.id)
    assert failed_job.status == JOB_STATUS_FAILED
    assert failed_job.attempts == 1
    assert failed_job.last_error == "Interpretation output does not match the required schema"
    with database.session() as session:
        snapshots = list(session.scalars(select(SessionInterpretationSnapshot)))
        assert len(snapshots) == 1
        assert snapshots[0].id == original_snapshot_id
        assert snapshots[0].job_id == first_claimed.id


def test_interpret_session_unexpected_interpreter_error_requeues_without_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    failed_claimed = claim_interpret_session_job(store, transcript_id)
    failing_interpreter = FailingInterpreter(RuntimeError("temporary model outage"))

    with pytest.raises(RuntimeError, match="temporary model outage"):
        JobRunner(database=database, interpreter=failing_interpreter).run(
            failed_claimed.id,
            failed_claimed.run_id,
            running_pid=123,
            now=at(10),
        )

    failed_job = get_job(database, failed_claimed.id)
    assert failed_job.status == JOB_STATUS_QUEUED
    assert failed_job.attempts == 1
    assert failed_job.last_error == "temporary model outage"
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionInterpretationSnapshot)) == 0


def test_wrong_run_id_is_rejected_without_incrementing_attempts(database: Database, store: JobStore) -> None:
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    with pytest.raises(JobRunTokenMismatchError):
        JobRunner(database=database).run(claimed.id, "wrong-run", now=at(10, 1))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_CLAIMED
    assert job.attempts == 0


@pytest.mark.parametrize(
    ("payload_json", "expected_error"),
    [
        ({}, InvalidJobPayloadError),
        ({"transcript_id": "not-an-int"}, InvalidJobPayloadError),
        ({"transcript_id": True}, InvalidJobPayloadError),
        ({"transcript_id": 99999}, TranscriptNotFoundError),
    ],
)
def test_bad_process_transcript_data_terminal_fails_after_start(
    database: Database,
    store: JobStore,
    payload_json: dict[str, object],
    expected_error: type[Exception],
) -> None:
    claimed = claim_process_transcript_job(store, payload_json=payload_json)

    with pytest.raises(expected_error):
        JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_FAILED
    assert job.attempts == 1
    assert job.exit_code == 1
    assert job.last_error


@pytest.mark.parametrize(
    ("payload_json", "expected_error"),
    [
        ([], InvalidJobPayloadError),
        ({}, InvalidJobPayloadError),
        ({"transcript_id": "not-an-int"}, InvalidJobPayloadError),
        ({"transcript_id": True}, InvalidJobPayloadError),
        ({"transcript_id": 1, "analysis_run_id": "not-an-int"}, InvalidJobPayloadError),
        ({"transcript_id": 1, "analysis_run_id": False}, InvalidJobPayloadError),
        ({"transcript_id": 1, "process_job_id": "not-an-int"}, InvalidJobPayloadError),
        ({"transcript_id": 1, "process_job_id": False}, InvalidJobPayloadError),
        ({"transcript_id": 99999}, TranscriptNotFoundError),
    ],
)
def test_bad_interpret_session_data_terminal_fails_after_start(
    database: Database,
    store: JobStore,
    payload_json: object,
    expected_error: type[Exception],
) -> None:
    claimed = claim_interpret_session_job(store, payload_json=payload_json)

    with pytest.raises(expected_error):
        JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_FAILED
    assert job.attempts == 1
    assert job.exit_code == 1
    assert job.last_error


def test_unsupported_job_kind_terminal_fails_after_start(database: Database, store: JobStore) -> None:
    store.enqueue("unknown_kind", payload_json={}, due_at=at(10))
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None

    with pytest.raises(UnsupportedJobKindError):
        JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    job = get_job(database, claimed.id)
    assert job.status == JOB_STATUS_FAILED
    assert job.attempts == 1
    assert job.exit_code == 1
    assert job.last_error == "Unsupported job kind: unknown_kind"
