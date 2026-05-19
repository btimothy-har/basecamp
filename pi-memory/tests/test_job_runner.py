from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pi_memory.analysis import TranscriptAnalysisResult, analyze_transcript_structure
from pi_memory.db import (
    ACTIVITY_TEXT_KIND_DETERMINISTIC,
    ACTIVITY_TEXT_KIND_TOOL_SUMMARY,
    ACTIVITY_TEXT_KIND_UNAVAILABLE,
    ACTIVITY_TEXT_STATUS_COMPLETED,
    ACTIVITY_TEXT_STATUS_FAILED,
    ACTIVITY_TEXT_STATUS_PENDING,
    ANALYSIS_STATUS_COMPLETED,
    EPISODE_INTERPRETATION_STATUS_COMPLETED,
    EPISODE_INTERPRETATION_STATUS_FAILED,
    JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
    JOB_KIND_INTERPRET_SESSION,
    JOB_KIND_PROCESS_TRANSCRIPT,
    JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
    JOB_STATUS_CLAIMED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PARENT_TRANSCRIPT_NOT_INGESTED,
    SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
    SESSION_INTERPRETATION_BLOCKED_REASON_SOURCE_ORIGIN_INCOMPLETE,
    SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION,
    SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES,
    SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
    SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED,
    SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
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
    EpisodeInterpretationSnapshot,
    EpisodeManifest,
    Job,
    MemorySession,
    SessionInterpretationQualityReport,
    SessionInterpretationSnapshot,
    SessionSnapshotShell,
    Transcript,
    TranscriptEntry,
)
from pi_memory.interpretation import (
    INTERPRETATION_PROMPT_VERSION,
    INTERPRETATION_SCHEMA_VERSION,
    DeterministicSessionInterpreter,
    DeterministicToolActivitySummarizer,
    InterpretationResult,
    InterpretationValidationError,
    InterpreterUnavailableError,
    ToolActivitySummarizer,
    ToolActivitySummaryInput,
    ToolActivitySummaryOutput,
    ToolActivitySummaryResult,
    build_source_ref_aliases,
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
from pi_memory.quality import (
    DeterministicQualityAssessor,
    QualityPacket,
    QualityReportDraft,
    validate_quality_assessment_output,
)
from pi_memory.settings import (
    INTERPRETATION_MODEL_ENV,
    QUALITY_MODEL_ENV,
    TOOL_SUMMARY_CONCURRENCY_ENV,
    TOOL_SUMMARY_MODEL_ENV,
    MissingInterpretationModelError,
)
from sqlalchemy import delete, func, select, text


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


@pytest.fixture(autouse=True)
def clear_interpretation_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    monkeypatch.delenv(QUALITY_MODEL_ENV, raising=False)
    monkeypatch.delenv(TOOL_SUMMARY_MODEL_ENV, raising=False)
    monkeypatch.delenv(TOOL_SUMMARY_CONCURRENCY_ENV, raising=False)


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


class AliasedInterpreter:
    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        result = DeterministicSessionInterpreter().interpret(packet)
        aliases = build_source_ref_aliases(packet)
        output = result.output
        return InterpretationResult(
            output=output.model_copy(
                update={
                    "claims": [
                        claim.model_copy(
                            update={
                                "source_ref_ids": [
                                    aliases.alias_for(source_ref_id) for source_ref_id in claim.source_ref_ids
                                ],
                            },
                        )
                        for claim in output.claims
                    ],
                    "open_questions": [
                        question.model_copy(
                            update={
                                "source_ref_ids": [
                                    aliases.alias_for(source_ref_id) for source_ref_id in question.source_ref_ids
                                ],
                            },
                        )
                        for question in output.open_questions
                    ],
                    "citations": [
                        citation.model_copy(update={"source_ref_id": aliases.alias_for(citation.source_ref_id)})
                        for citation in output.citations
                    ],
                },
            ),
            model_metadata=result.model_metadata,
            prompt_version=result.prompt_version,
        )


class FailingInterpreter:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error if error is not None else AssertionError("interpreter should not be called")

    def interpret(self, _packet: InterpretationPacket) -> InterpretationResult:
        self.calls += 1
        raise self.error


class EpisodeOrdinalFailingInterpreter:
    def __init__(self, failing_ordinal: int) -> None:
        self.failing_ordinal = failing_ordinal
        self.calls: list[InterpretationPacket] = []

    def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
        self.calls.append(packet)
        if packet.episode_packets[0].ordinal == self.failing_ordinal:
            raise RuntimeError("RAW_EPISODE_FAILURE_SHOULD_NOT_LEAK")
        return DeterministicSessionInterpreter().interpret(packet)


class ProviderShouldNotLeakError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("RAW_PROVIDER_ERROR_SHOULD_NOT_LEAK")


class RecordingQualityAssessor:
    def __init__(self) -> None:
        self.calls: list[QualityPacket] = []

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        self.calls.append(packet)
        return DeterministicQualityAssessor().assess(packet)

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        return self.assess(packet)


class AliasedQualityAssessor:
    def __init__(self) -> None:
        self.calls: list[QualityPacket] = []

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        self.calls.append(packet)
        output = validate_quality_assessment_output(
            {
                "semantic_status": SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED,
                "findings": [
                    {
                        "code": "review_source_support",
                        "severity": "warning",
                        "message": "Source s0001 needs review.",
                        "references": [{"kind": "source_ref", "id": "s0001"}],
                    },
                ],
                "claim_assessments": [
                    {
                        "claim_index": 0,
                        "status": "supported",
                        "source_ref_ids": ["s0001"],
                        "rationale": "s0001 supports this claim.",
                    },
                ],
                "missing_high_signal_items": [
                    {
                        "kind": "decision",
                        "description": "A decision near s0001 was missed.",
                        "source_ref_ids": ["s0001"],
                    },
                ],
            },
            packet,
        )
        return QualityReportDraft(
            quality_status=SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY,
            quality_reason=None,
            derivation_status=packet.deterministic_report.derivation_status,
            deterministic_status=packet.deterministic_report.deterministic_status,
            semantic_status=output.semantic_status,
            promotable=True,
            deterministic_findings=list(packet.deterministic_report.deterministic_findings),
            semantic_findings=list(output.findings),
            claim_assessments=list(output.claim_assessments),
            missing_high_signal_items=list(output.missing_high_signal_items),
            model_metadata={"provider": "test", "model": "alias-quality", "mode": "test"},
            prompt_version="test-quality-alias-v1",
        )

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        return self.assess(packet)


class FailingQualityAssessor:
    def __init__(self) -> None:
        self.calls: list[QualityPacket] = []

    def assess(self, packet: QualityPacket) -> QualityReportDraft:
        self.calls.append(packet)
        raise ProviderShouldNotLeakError()

    async def assess_async(self, packet: QualityPacket) -> QualityReportDraft:
        return self.assess(packet)


class PartiallyFailingToolSummarizer:
    def __init__(self) -> None:
        self.calls: list[ToolActivitySummaryInput] = []

    def summarize(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        self.calls.append(summary_input)
        if len(self.calls) == 1:
            raise RuntimeError("RAW_TOOL_OUTPUT_SHOULD_NOT_LEAK")
        output = ToolActivitySummaryOutput(
            summary="The second tool result was summarized.",
            cited_source_entry_ids=[entry.row_id for entry in summary_input.source_entries],
        )
        return ToolActivitySummaryResult(
            output=output,
            model_metadata={"provider": "test", "model": "fake", "mode": "fake", "schema_version": 1},
            prompt_version="fake-tool-summary-v1",
        )

    async def summarize_async(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        return self.summarize(summary_input)


class RecordingConcurrentToolSummarizer:
    def __init__(self) -> None:
        self.calls: list[ToolActivitySummaryInput] = []
        self.active_calls = 0
        self.max_active_calls = 0

    def summarize(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        output = ToolActivitySummaryOutput(
            summary=f"Tool activity {summary_input.activity_unit_id} was summarized.",
            cited_source_entry_ids=[entry.row_id for entry in summary_input.source_entries],
        )
        return ToolActivitySummaryResult(
            output=output,
            model_metadata={"provider": "test", "model": "fake", "mode": "fake", "schema_version": 1},
            prompt_version="fake-tool-summary-v1",
        )

    async def summarize_async(self, summary_input: ToolActivitySummaryInput) -> ToolActivitySummaryResult:
        self.calls.append(summary_input)
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        await asyncio.sleep(0)
        self.active_calls -= 1
        return self.summarize(summary_input)


def summarize_with_protocol(
    summarizer: ToolActivitySummarizer,
    summary_input: ToolActivitySummaryInput,
) -> ToolActivitySummaryResult:
    return summarizer.summarize(summary_input)


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


def create_tool_pair_transcript(database: Database, count: int, session_id: str = "pi-session-tools") -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id=session_id)
        transcript = Transcript(session=memory_session, path=f"/tmp/pi/{session_id}.jsonl")
        session.add(transcript)
        session.flush()
        for index in range(count):
            call_id = f"call-{index + 1}"
            add_transcript_entry(
                session,
                transcript_id=transcript.id,
                entry_id=call_id,
                entry_type="message",
                message_role="assistant",
                raw_line=raw_message(
                    "assistant",
                    [
                        {
                            "type": "toolCall",
                            "id": call_id,
                            "name": "bash",
                            "arguments": {"command": f"printf {index + 1}"},
                        },
                    ],
                ),
                byte_start=index * 200,
            )
            add_transcript_entry(
                session,
                transcript_id=transcript.id,
                entry_id=f"result-{index + 1}",
                entry_type="message",
                message_role="toolResult",
                raw_line=raw_message(
                    "toolResult",
                    f"output {index + 1}",
                    toolCallId=call_id,
                    isError=False,
                ),
                byte_start=index * 200 + 100,
            )
        session.flush()
        return transcript.id


def create_two_tool_pair_transcript(database: Database) -> int:
    return create_tool_pair_transcript(database, 2, session_id="pi-session-two-tools")


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


def enqueue_quality_job(store: JobStore, snapshot_id: int, *, max_attempts: int = 3) -> Job:
    return store.enqueue(
        JOB_KIND_ASSESS_INTERPRETATION_QUALITY,
        payload_json={"snapshot_id": snapshot_id, "session_id": "pi-session-1"},
        due_at=at(10),
        max_attempts=max_attempts,
    )


def claim_quality_job(store: JobStore, job_id: int) -> Job:
    claimed = store.claim_next("worker-quality")
    assert claimed is not None
    assert claimed.id == job_id
    return claimed


def analyze_transcript(database: Database, transcript_id: int, job_id: int | None = None) -> TranscriptAnalysisResult:
    with database.session() as session:
        transcript = session.get_one(Transcript, transcript_id)
        return analyze_transcript_structure(session, transcript, job_id=job_id)


def claim_summarize_tool_activities_job(
    store: JobStore,
    *,
    transcript_id: int,
    session_id: str,
    analysis_result: TranscriptAnalysisResult,
    process_job_id: int | None = None,
) -> Job:
    summarize_job = store.enqueue(
        JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
        payload_json={
            "transcript_id": transcript_id,
            "analysis_run_id": analysis_result.analysis_run_id,
            "session_id": session_id,
            "process_job_id": process_job_id,
            "analyzed_through_entry_id": analysis_result.analyzed_through_entry_id,
            "analyzed_through_byte_offset": analysis_result.analyzed_through_byte_offset,
            "activity_count": analysis_result.activity_count,
            "episode_count": analysis_result.episode_count,
            "manifest_count": analysis_result.manifest_count,
        },
        due_at=at(10),
    )
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None
    assert claimed.id == summarize_job.id
    return claimed


def process_transcript(database: Database, store: JobStore, transcript_id: int) -> Job:
    claimed = claim_process_transcript_job(store, transcript_id)
    return JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))


def run_summarize_tool_activities_job(
    database: Database,
    store: JobStore,
    job_id: int,
    tool_summarizer: ToolActivitySummarizer | None = None,
) -> Job:
    claimed = store.claim_next("worker-summarize")
    assert claimed is not None
    assert claimed.id == job_id
    return JobRunner(database=database, tool_summarizer=tool_summarizer).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )


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
    summarize_tool_activities_job_id = completed.result_json["summarize_tool_activities_job_id"]
    assert isinstance(summarize_tool_activities_job_id, int)
    base_result = {
        key: value
        for key, value in completed.result_json.items()
        if key not in {"phase_5a", "summarize_tool_activities_job_id"}
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
        summarize_job = session.get_one(Job, summarize_tool_activities_job_id)
        assert summarize_job.kind == JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES
        assert summarize_job.status == JOB_STATUS_QUEUED
        assert summarize_job.payload_json == {
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
        assert "raw_line" not in summarize_job.payload_json

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


def test_summarize_tool_activities_updates_tool_pair_text_and_enqueues_interpretation(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_resolved_fork_child_transcript(database)
    analysis_result = analyze_transcript(database, transcript_id)
    claimed = claim_summarize_tool_activities_job(
        store,
        transcript_id=transcript_id,
        session_id="pi-child-session",
        analysis_result=analysis_result,
    )

    completed = JobRunner(
        database=database,
        tool_summarizer=DeterministicToolActivitySummarizer(),
    ).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["status"] == "completed"
    assert completed.result_json["tool_pair_activity_count"] == 1
    assert completed.result_json["summarized_activity_count"] == 1
    assert completed.result_json["failed_activity_count"] == 0
    assert isinstance(completed.result_json["interpret_session_job_id"], int)
    assert "ok" not in str(completed.result_json)

    with database.session() as session:
        tool_activity = session.scalar(
            select(ActivityUnit).where(
                ActivityUnit.analysis_run_id == analysis_result.analysis_run_id,
                ActivityUnit.kind == "tool_pair",
            ),
        )
        assert tool_activity is not None
        assert tool_activity.activity_text_kind == ACTIVITY_TEXT_KIND_TOOL_SUMMARY
        assert tool_activity.activity_text_status == ACTIVITY_TEXT_STATUS_COMPLETED
        assert tool_activity.activity_text == (
            "Tool summary:\nTool bash completed with result status success.\nOutcome: is_error=False"
        )
        assert tool_activity.activity_text_metadata_json["producer"] == "tool_activity_summarizer"
        assert tool_activity.activity_text_metadata_json["prompt_version"] == "phase5b-tool-activity-summary-v1"
        assert tool_activity.activity_text_metadata_json["model_metadata"] == {
            "provider": "pi-memory",
            "model": "deterministic-tool-activity-summarizer-v1",
            "mode": "deterministic",
        }

        interpret_job = session.get_one(Job, completed.result_json["interpret_session_job_id"])
        assert interpret_job.kind == JOB_KIND_INTERPRET_SESSION
        assert interpret_job.payload_json["analysis_run_id"] == analysis_result.analysis_run_id
        assert interpret_job.payload_json["transcript_id"] == transcript_id
        assert "raw_line" not in str(interpret_job.payload_json)


def test_summarize_tool_activities_handles_zero_tool_pairs_without_model(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_id = create_transcript(database)
    analysis_result = analyze_transcript(database, transcript_id)
    claimed = claim_summarize_tool_activities_job(
        store,
        transcript_id=transcript_id,
        session_id="pi-session-1",
        analysis_result=analysis_result,
    )

    def fail_factory() -> None:
        pytest.fail("summarizer factory should not be called when there are no tool pairs")

    monkeypatch.setattr("pi_memory.jobs.runner.create_tool_activity_summarizer", fail_factory)
    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.result_json is not None
    assert completed.result_json["tool_pair_activity_count"] == 0
    assert completed.result_json["summarized_activity_count"] == 0
    assert completed.result_json["failed_activity_count"] == 0
    assert isinstance(completed.result_json["interpret_session_job_id"], int)


def test_summarize_tool_activities_records_partial_failures_without_leaking_errors(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_two_tool_pair_transcript(database)
    analysis_result = analyze_transcript(database, transcript_id)
    claimed = claim_summarize_tool_activities_job(
        store,
        transcript_id=transcript_id,
        session_id="pi-session-two-tools",
        analysis_result=analysis_result,
    )
    summarizer = PartiallyFailingToolSummarizer()

    completed = JobRunner(database=database, tool_summarizer=summarizer).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.result_json is not None
    assert completed.result_json["tool_pair_activity_count"] == 2
    assert completed.result_json["summarized_activity_count"] == 1
    assert completed.result_json["failed_activity_count"] == 1
    assert "RAW_TOOL_OUTPUT_SHOULD_NOT_LEAK" not in str(completed.result_json)
    assert len(summarizer.calls) == 2

    with database.session() as session:
        activities = list(
            session.scalars(
                select(ActivityUnit)
                .where(ActivityUnit.analysis_run_id == analysis_result.analysis_run_id)
                .order_by(ActivityUnit.ordinal),
            ),
        )
        assert [activity.activity_text_status for activity in activities] == [
            ACTIVITY_TEXT_STATUS_FAILED,
            ACTIVITY_TEXT_STATUS_COMPLETED,
        ]
        assert activities[0].activity_text is None
        assert activities[0].activity_text_metadata_json == {
            "version": 1,
            "producer": "tool_activity_summarizer",
            "status": "failed",
            "error_type": "RuntimeError",
        }
        assert activities[1].activity_text == "Tool summary:\nThe second tool result was summarized."


def test_summarize_tool_activities_runs_single_tool_calls_with_configured_concurrency(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(TOOL_SUMMARY_CONCURRENCY_ENV, "12")
    transcript_id = create_tool_pair_transcript(database, 12, session_id="pi-session-concurrent-tools")
    analysis_result = analyze_transcript(database, transcript_id)
    claimed = claim_summarize_tool_activities_job(
        store,
        transcript_id=transcript_id,
        session_id="pi-session-concurrent-tools",
        analysis_result=analysis_result,
    )
    summarizer = RecordingConcurrentToolSummarizer()

    completed = JobRunner(database=database, tool_summarizer=summarizer).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.result_json is not None
    assert completed.result_json["tool_pair_activity_count"] == 12
    assert completed.result_json["summarized_activity_count"] == 12
    assert completed.result_json["failed_activity_count"] == 0
    assert len(summarizer.calls) == 12
    assert summarizer.max_active_calls == 12
    assert all(len(call.source_entries) == 2 for call in summarizer.calls)


def test_summarize_tool_activities_stale_analysis_is_noop(database: Database, store: JobStore) -> None:
    transcript_id = create_resolved_fork_child_transcript(database)
    analysis_result = analyze_transcript(database, transcript_id)
    stale_job = store.enqueue(
        JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES,
        payload_json={"transcript_id": transcript_id, "analysis_run_id": analysis_result.analysis_run_id + 100},
        due_at=at(10),
    )
    claimed = store.claim_next("worker-1", now=at(10))
    assert claimed is not None
    assert claimed.id == stale_job.id

    completed = JobRunner(
        database=database,
        tool_summarizer=DeterministicToolActivitySummarizer(),
    ).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.result_json is not None
    assert completed.result_json == {
        "status": "stale",
        "is_stale": True,
        "transcript_id": transcript_id,
        "analysis_run_id": analysis_result.analysis_run_id + 100,
        "process_job_id": None,
        "interpret_session_job_id": None,
        "tool_pair_activity_count": 0,
        "summarized_activity_count": 0,
        "failed_activity_count": 0,
    }


def test_summarize_tool_activities_stale_process_job_is_noop(database: Database, store: JobStore) -> None:
    transcript_id = create_resolved_fork_child_transcript(database)
    process_job = store.enqueue(JOB_KIND_PROCESS_TRANSCRIPT, payload_json={"transcript_id": transcript_id})
    analysis_result = analyze_transcript(database, transcript_id, job_id=process_job.id)
    claimed = claim_summarize_tool_activities_job(
        store,
        transcript_id=transcript_id,
        session_id="pi-child-session",
        analysis_result=analysis_result,
        process_job_id=process_job.id + 1,
    )

    completed = JobRunner(
        database=database,
        tool_summarizer=DeterministicToolActivitySummarizer(),
    ).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.result_json is not None
    assert completed.result_json["status"] == "stale"
    assert completed.result_json["interpret_session_job_id"] is None


def test_process_transcript_without_interpretation_model_still_succeeds_lazily(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)

    def fail_factory() -> None:
        pytest.fail("model factories should not be called for process_transcript")

    monkeypatch.setattr("pi_memory.jobs.runner.create_session_interpreter", fail_factory)
    monkeypatch.setattr("pi_memory.jobs.runner.create_tool_activity_summarizer", fail_factory)
    transcript_id = create_transcript(database)
    claimed = claim_process_transcript_job(store, transcript_id)

    completed = JobRunner(database=database).run(claimed.id, claimed.run_id, running_pid=123, now=at(10))

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert isinstance(completed.result_json["summarize_tool_activities_job_id"], int)


def test_process_transcript_enqueued_interpret_job_writes_snapshot(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    summarize_job = run_summarize_tool_activities_job(
        database,
        store,
        process.result_json["summarize_tool_activities_job_id"],
    )
    assert summarize_job.result_json is not None
    interpret_session_job_id = summarize_job.result_json["interpret_session_job_id"]

    claimed = store.claim_next("worker-interpret")
    assert claimed is not None
    assert claimed.id == interpret_session_job_id
    completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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


def test_interpret_session_alias_output_persists_canonical_source_refs(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    summarize_job = run_summarize_tool_activities_job(
        database,
        store,
        process.result_json["summarize_tool_activities_job_id"],
    )
    assert summarize_job.result_json is not None
    claimed = store.claim_next("worker-interpret")
    assert claimed is not None
    assert claimed.id == summarize_job.result_json["interpret_session_job_id"]

    completed = JobRunner(database=database, interpreter=AliasedInterpreter()).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
    )

    assert completed.status == JOB_STATUS_COMPLETED
    with database.session() as session:
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.status == SESSION_INTERPRETATION_STATUS_COMPLETED
        canonical_id = snapshot.interpretation_json["claims"][0]["source_ref_ids"][0]
        assert canonical_id.startswith("ar")
        assert snapshot.interpretation_json["citations"][0]["source_ref_id"] == canonical_id
        assert {citation["source_ref_id"] for citation in snapshot.citations_json} == {canonical_id}
        assert "s0001" not in json.dumps(snapshot.interpretation_json)
        assert "s0001" not in json.dumps(snapshot.citations_json)


def test_process_transcript_enqueued_interpret_job_writes_snapshot_without_snapshot_shells(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    summarize_job_id = process.result_json["summarize_tool_activities_job_id"]
    analysis_run_id = process.result_json["phase_5a"]["analysis_run_id"]

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 1
        session.execute(delete(SessionSnapshotShell))
        session.flush()
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 0

    summarize_job = run_summarize_tool_activities_job(database, store, summarize_job_id)
    assert summarize_job.result_json is not None
    interpret_session_job_id = summarize_job.result_json["interpret_session_job_id"]

    claimed = store.claim_next("worker-interpret")
    assert claimed is not None
    assert claimed.id == interpret_session_job_id
    completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["status"] == SESSION_INTERPRETATION_STATUS_COMPLETED
    assert completed.result_json["analysis_run_id"] == analysis_run_id
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionSnapshotShell)) == 0
        snapshot = session.scalar(select(SessionInterpretationSnapshot))
        assert snapshot is not None
        assert snapshot.job_id == interpret_session_job_id
        assert snapshot.analysis_run_id == analysis_run_id
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
        assert [activity.activity_text_kind for activity in activities] == [
            ACTIVITY_TEXT_KIND_DETERMINISTIC,
            ACTIVITY_TEXT_KIND_DETERMINISTIC,
        ]
        assert [activity.activity_text_status for activity in activities] == [
            ACTIVITY_TEXT_STATUS_COMPLETED,
            ACTIVITY_TEXT_STATUS_COMPLETED,
        ]
        assert activities[0].activity_text == "User message:\nfind nebula notes"
        assert activities[0].activity_text_metadata_json["producer"] == "phase_5a_deterministic"
        assert activities[1].activity_text == "Custom event: message."
        assert "do not expose" not in activities[1].activity_text
        assert "raw_line" not in str([activity.activity_text_metadata_json for activity in activities])

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
        assert activities[0].activity_text == "Session event: session; fields: cwd, type."
        assert activities[0].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_LOCAL: activities[0].source_entry_ids_json,
        }
        assert activities[1].kind == "user_text"
        assert activities[1].source_metadata_json["source_entry_ids_by_origin"] == {
            SOURCE_ORIGIN_INHERITED: activities[1].source_entry_ids_json,
        }
        assert activities[2].kind == "tool_pair"
        assert activities[2].activity_text is None
        assert activities[2].activity_text_kind == ACTIVITY_TEXT_KIND_UNAVAILABLE
        assert activities[2].activity_text_status == ACTIVITY_TEXT_STATUS_PENDING
        assert activities[2].activity_text_metadata_json["reason"] == "awaiting_tool_summary"
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
        assert activities[1].activity_text == "Compaction summary:\ncompacted earlier context"
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
    first_summarize_job_id = first_completed.result_json["summarize_tool_activities_job_id"]
    assert isinstance(first_summarize_job_id, int)

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
    second_summarize_job_id = second_completed.result_json["summarize_tool_activities_job_id"]
    assert isinstance(second_summarize_job_id, int)
    assert second_summarize_job_id != first_summarize_job_id

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
        first_summarize_job = session.get_one(Job, first_summarize_job_id)
        second_summarize_job = session.get_one(Job, second_summarize_job_id)
        assert first_summarize_job.kind == JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES
        assert second_summarize_job.kind == JOB_KIND_SUMMARIZE_TOOL_ACTIVITIES
        assert first_summarize_job.payload_json["analysis_run_id"] == first_phase_5a["analysis_run_id"]
        assert first_summarize_job.payload_json["process_job_id"] == first_claimed.id
        assert second_summarize_job.payload_json["analysis_run_id"] == second_phase_5a["analysis_run_id"]
        assert second_summarize_job.payload_json["process_job_id"] == second_claimed.id

    stale_claimed = store.claim_next("worker-summarize")
    assert stale_claimed is not None
    assert stale_claimed.id == first_summarize_job_id
    stale_completed = JobRunner(database=database).run(
        stale_claimed.id,
        stale_claimed.run_id,
        running_pid=123,
    )
    assert stale_completed.result_json is not None
    assert stale_completed.result_json["status"] == "stale"
    assert stale_completed.result_json["is_stale"] is True
    assert stale_completed.result_json["interpret_session_job_id"] is None
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
        assert snapshot.interpretation_json["summary"].startswith("Episode-level interpretation")
        assert snapshot.interpretation_json["aggregation"]["aggregation_mode"] == "episode_claim_concat"
        assert snapshot.interpretation_json["aggregation"]["coverage_status"] == "complete"
        assert snapshot.citations_json
        assert snapshot.model_metadata_json["provider"] == "pi-memory"

    quality_job_id = completed.result_json["assess_interpretation_quality_job_id"]
    quality_job = get_job(database, quality_job_id)
    assert quality_job.kind == JOB_KIND_ASSESS_INTERPRETATION_QUALITY
    assert quality_job.payload_json["snapshot_id"] == completed.result_json["snapshot_id"]
    assert quality_job.payload_json["interpretation_job_id"] == claimed.id


def test_interpret_session_interprets_each_claim_source_episode_separately(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_compaction_boundary_transcript(database)
    process_transcript(database, store, transcript_id)
    interpreter = RecordingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert len(interpreter.calls) == 2
    assert [call.readiness.episode_count for call in interpreter.calls] == [1, 1]
    assert [call.episode_packets[0].ordinal for call in interpreter.calls] == [0, 1]
    assert completed.result_json is not None
    assert completed.result_json["episode_interpretation"]["coverage_status"] == "complete"
    with database.session() as session:
        episode_rows = list(
            session.scalars(
                select(EpisodeInterpretationSnapshot).order_by(EpisodeInterpretationSnapshot.episode_ordinal),
            ),
        )
        snapshot = session.scalar(select(SessionInterpretationSnapshot))

    assert [row.status for row in episode_rows] == [
        EPISODE_INTERPRETATION_STATUS_COMPLETED,
        EPISODE_INTERPRETATION_STATUS_COMPLETED,
    ]
    assert snapshot is not None
    assert len(snapshot.interpretation_json["claims"]) == 2
    assert snapshot.interpretation_json["aggregation"] == completed.result_json["episode_interpretation"]


def test_interpret_session_persists_partial_episode_failures(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_compaction_boundary_transcript(database)
    process_transcript(database, store, transcript_id)
    interpreter = EpisodeOrdinalFailingInterpreter(failing_ordinal=1)
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert len(interpreter.calls) == 2
    assert completed.result_json is not None
    assert completed.result_json["episode_interpretation"]["coverage_status"] == "partial"
    assert completed.result_json["episode_interpretation"]["completed_episode_count"] == 1
    assert completed.result_json["episode_interpretation"]["failed_episode_count"] == 1
    assert "RAW_EPISODE_FAILURE_SHOULD_NOT_LEAK" not in str(completed.result_json)
    with database.session() as session:
        episode_rows = list(
            session.scalars(
                select(EpisodeInterpretationSnapshot).order_by(EpisodeInterpretationSnapshot.episode_ordinal),
            ),
        )
        snapshot = session.scalar(select(SessionInterpretationSnapshot))

    assert [row.status for row in episode_rows] == [
        EPISODE_INTERPRETATION_STATUS_COMPLETED,
        EPISODE_INTERPRETATION_STATUS_FAILED,
    ]
    assert episode_rows[1].failure_metadata_json == {"error_type": "RuntimeError"}
    assert snapshot is not None
    assert len(snapshot.interpretation_json["claims"]) == 1
    assert snapshot.interpretation_json["aggregation"]["coverage_status"] == "partial"


def test_assess_quality_completed_snapshot_writes_semantic_report(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    analyze_transcript(database, transcript_id)
    interpreter = RecordingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)
    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    quality_job_id = completed.result_json["assess_interpretation_quality_job_id"]
    quality_assessor = RecordingQualityAssessor()
    claimed_quality = claim_quality_job(store, quality_job_id)

    quality = JobRunner(database=database, quality_assessor=quality_assessor).run(
        claimed_quality.id,
        claimed_quality.run_id,
        running_pid=123,
        now=at(10),
    )

    assert quality.status == JOB_STATUS_COMPLETED
    assert quality.result_json is not None
    assert quality.result_json["quality_status"] == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
    assert quality.result_json["quality_reason"] is None
    assert quality.result_json["semantic_status"] == SESSION_INTERPRETATION_SEMANTIC_STATUS_PASSED
    assert quality.result_json["promotable"] is True
    assert len(quality_assessor.calls) == 1
    with database.session() as session:
        report = session.scalar(select(SessionInterpretationQualityReport))
        assert report is not None
        assert report.snapshot_id == completed.result_json["snapshot_id"]
        assert report.job_id == quality_job_id
        assert report.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_HEALTHY
        assert report.quality_reason is None
        assert report.promotable is True
        assert report.model_metadata_json["model"] == "deterministic-quality-assessor-v1"


def test_assess_quality_alias_output_persists_canonical_source_refs(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    analyze_transcript(database, transcript_id)
    claimed = claim_interpret_session_job(store, transcript_id)
    completed = JobRunner(database=database, interpreter=RecordingInterpreter()).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    quality_job_id = completed.result_json["assess_interpretation_quality_job_id"]
    quality_assessor = AliasedQualityAssessor()
    claimed_quality = claim_quality_job(store, quality_job_id)

    JobRunner(database=database, quality_assessor=quality_assessor).run(
        claimed_quality.id,
        claimed_quality.run_id,
        running_pid=123,
        now=at(10),
    )

    assert len(quality_assessor.calls) == 1
    with database.session() as session:
        snapshot = session.get_one(SessionInterpretationSnapshot, completed.result_json["snapshot_id"])
        canonical_source_ref_id = snapshot.citations_json[0]["source_ref_id"]
        report = session.scalar(select(SessionInterpretationQualityReport))
        assert report is not None
        assert report.claim_assessments_json[0]["source_ref_ids"] == [canonical_source_ref_id]
        assert report.missing_high_signal_items_json[0]["source_ref_ids"] == [canonical_source_ref_id]
        assert report.semantic_findings_json[0]["references"][0]["id"] == canonical_source_ref_id
        assert "s0001" not in json.dumps(
            {
                "claim_assessments": report.claim_assessments_json,
                "missing_high_signal_items": report.missing_high_signal_items_json,
                "semantic_findings": report.semantic_findings_json,
            },
        )


def test_assess_quality_blocked_snapshot_writes_non_model_report(database: Database, store: JobStore) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_BLOCKED,
            blocked_reason=SESSION_INTERPRETATION_BLOCKED_REASON_PHASE_5A_NOT_READY,
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
    job = enqueue_quality_job(store, snapshot_id)
    quality_assessor = FailingQualityAssessor()
    claimed = claim_quality_job(store, job.id)

    completed = JobRunner(database=database, quality_assessor=quality_assessor).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["quality_status"] == SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED
    assert completed.result_json["quality_reason"] == SESSION_INTERPRETATION_QUALITY_REASON_BLOCKED_INTERPRETATION
    assert completed.result_json["semantic_status"] == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
    assert quality_assessor.calls == []


def test_assess_quality_skipped_snapshot_writes_non_model_report(database: Database, store: JobStore) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
    job = enqueue_quality_job(store, snapshot_id)
    quality_assessor = FailingQualityAssessor()
    claimed = claim_quality_job(store, job.id)

    completed = JobRunner(database=database, quality_assessor=quality_assessor).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["quality_status"] == SESSION_INTERPRETATION_QUALITY_STATUS_NOT_ASSESSED
    assert completed.result_json["quality_reason"] == SESSION_INTERPRETATION_QUALITY_REASON_SKIPPED_NO_CLAIM_SOURCES
    assert completed.result_json["semantic_status"] == SESSION_INTERPRETATION_SEMANTIC_STATUS_NOT_ASSESSED
    assert quality_assessor.calls == []


def test_assess_quality_deleted_snapshot_is_stale_noop(database: Database, store: JobStore) -> None:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-1")
        snapshot = SessionInterpretationSnapshot(
            session=memory_session,
            status=SESSION_INTERPRETATION_STATUS_SKIPPED_NO_CLAIM_SOURCES,
        )
        session.add(snapshot)
        session.flush()
        snapshot_id = snapshot.id
        session.delete(snapshot)

    job = enqueue_quality_job(store, snapshot_id)
    claimed = claim_quality_job(store, job.id)

    completed = JobRunner(database=database, quality_assessor=FailingQualityAssessor()).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json == {
        "status": "stale",
        "snapshot_id": snapshot_id,
        "quality_report_id": None,
        "stale_reason": "snapshot_not_found",
    }
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionInterpretationQualityReport)) == 0


def test_assess_quality_final_failure_writes_assessment_failed_report(
    database: Database,
    store: JobStore,
) -> None:
    transcript_id = create_transcript(database)
    analyze_transcript(database, transcript_id)
    claimed = claim_interpret_session_job(store, transcript_id)
    completed = JobRunner(database=database, interpreter=RecordingInterpreter()).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    snapshot_id = completed.result_json["snapshot_id"]
    job = enqueue_quality_job(store, snapshot_id, max_attempts=1)
    claimed_quality = claim_quality_job(store, job.id)

    with pytest.raises(ProviderShouldNotLeakError, match="RAW_PROVIDER_ERROR_SHOULD_NOT_LEAK"):
        JobRunner(database=database, quality_assessor=FailingQualityAssessor()).run(
            claimed_quality.id,
            claimed_quality.run_id,
            running_pid=123,
            now=at(10),
        )

    failed_job = get_job(database, job.id)
    assert failed_job.status == JOB_STATUS_FAILED
    assert failed_job.last_error == "ProviderShouldNotLeakError"
    with database.session() as session:
        report = session.scalar(select(SessionInterpretationQualityReport))
        assert report is not None
        assert report.snapshot_id == snapshot_id
        assert report.quality_status == SESSION_INTERPRETATION_QUALITY_STATUS_ASSESSMENT_FAILED
        assert report.quality_reason == SESSION_INTERPRETATION_QUALITY_REASON_SEMANTIC_ASSESSMENT_FAILED
        assert report.semantic_status == SESSION_INTERPRETATION_SEMANTIC_STATUS_ASSESSMENT_FAILED
        assert report.promotable is False
        assert report.assessment_metadata_json["assessment_failed_error_type"] == "ProviderShouldNotLeakError"
        assert "RAW_PROVIDER_ERROR_SHOULD_NOT_LEAK" not in str(report.assessment_metadata_json)


def test_interpret_session_explicit_interpreter_bypasses_configured_factory(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "  ")

    def fail_factory() -> None:
        pytest.fail("explicit interpreter should bypass configured factory")

    monkeypatch.setattr("pi_memory.jobs.runner.create_session_interpreter", fail_factory)
    interpreter = RecordingInterpreter()
    claimed = claim_interpret_session_job(store, transcript_id)

    completed = JobRunner(database=database, interpreter=interpreter).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert len(interpreter.calls) == 1


def test_interpret_session_configured_pydantic_ai_uses_configured_model(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakePydanticAISessionInterpreter:
        instances: list[FakePydanticAISessionInterpreter] = []

        def __init__(self, model: str) -> None:
            self.model = model
            self.calls: list[InterpretationPacket] = []
            self.instances.append(self)

        def interpret(self, packet: InterpretationPacket) -> InterpretationResult:
            self.calls.append(packet)
            deterministic = DeterministicSessionInterpreter().interpret(packet)
            return InterpretationResult(
                output=deterministic.output,
                model_metadata={"provider": "openai", "model": self.model, "mode": "pydantic-ai"},
                prompt_version=deterministic.prompt_version,
            )

    monkeypatch.setenv(INTERPRETATION_MODEL_ENV, "openai:gpt-4.1-mini")
    monkeypatch.setattr(
        "pi_memory.interpretation.factory.PydanticAISessionInterpreter",
        FakePydanticAISessionInterpreter,
    )
    transcript_id = create_transcript(database)
    process = process_transcript(database, store, transcript_id)
    assert process.result_json is not None
    summarize_job = run_summarize_tool_activities_job(
        database,
        store,
        process.result_json["summarize_tool_activities_job_id"],
    )
    assert summarize_job.result_json is not None
    claimed = store.claim_next("worker-interpret")
    assert claimed is not None
    assert claimed.id == summarize_job.result_json["interpret_session_job_id"]

    completed = JobRunner(database=database).run(
        claimed.id,
        claimed.run_id,
        running_pid=123,
        now=at(10),
    )

    assert completed.status == JOB_STATUS_COMPLETED
    assert completed.result_json is not None
    assert completed.result_json["model_metadata"] == {
        "provider": "openai",
        "model": "openai:gpt-4.1-mini",
        "mode": "pydantic-ai",
    }
    assert len(FakePydanticAISessionInterpreter.instances) == 1
    assert FakePydanticAISessionInterpreter.instances[0].model == "openai:gpt-4.1-mini"
    assert len(FakePydanticAISessionInterpreter.instances[0].calls) == 1


def test_interpret_session_without_model_requeues_without_snapshot(
    database: Database,
    store: JobStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript_id = create_transcript(database)
    process_transcript(database, store, transcript_id)
    monkeypatch.delenv(INTERPRETATION_MODEL_ENV, raising=False)
    claimed = claim_interpret_session_job(store, transcript_id)

    with pytest.raises(MissingInterpretationModelError):
        JobRunner(database=database).run(
            claimed.id,
            claimed.run_id,
            running_pid=123,
            now=at(10),
        )

    failed_job = get_job(database, claimed.id)
    assert failed_job.status == JOB_STATUS_QUEUED
    assert failed_job.attempts == 1
    assert failed_job.last_error == "interpretation_model is required for session interpretation."
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(SessionInterpretationSnapshot)) == 0


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
    completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
    completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
    first_completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
    first_completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
        first_claimed.id,
        first_claimed.run_id,
        running_pid=123,
        now=at(10),
    )
    assert first_completed.result_json is not None

    second_claimed = claim_interpret_session_job(store, transcript_id)
    second_completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
    first_completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
    first_completed = JobRunner(database=database, interpreter=DeterministicSessionInterpreter()).run(
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
