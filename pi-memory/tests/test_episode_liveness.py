from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from pi_memory.analysis import (
    EPISODE_LIVENESS_STATUS_CLOSED,
    EPISODE_LIVENESS_STATUS_IDLE_ELIGIBLE,
    EPISODE_LIVENESS_STATUS_LIVE,
    episode_liveness_for_analysis,
)
from pi_memory.constants import (
    ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
    ANALYSIS_STATUS_COMPLETED,
    EPISODE_CLOSE_REASON_CURRENT_CURSOR,
    EPISODE_CLOSE_REASON_TIME_GAP,
    EPISODE_CLOSE_REASON_TRANSCRIPT_END,
    EPISODE_STATUS_CLOSED,
    EPISODE_STATUS_OPEN,
)
from pi_memory.db.database import Database
from pi_memory.db.models import AnalysisRun, Episode, MemorySession, Transcript

BASE_TIME = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def create_analysis_with_episodes(
    database: Database,
    episodes: tuple[dict[str, object], ...],
) -> int:
    with database.session() as session:
        memory_session = MemorySession(session_id="pi-session-liveness", cwd="/repo/basecamp")
        transcript = Transcript(
            session=memory_session,
            path="/tmp/liveness.jsonl",
            cursor_offset=1000,
            file_size=1000,
        )
        analysis_run = AnalysisRun(
            session=memory_session,
            transcript=transcript,
            analysis_kind=ANALYSIS_KIND_TRANSCRIPT_STRUCTURE,
            status=ANALYSIS_STATUS_COMPLETED,
            analyzed_through_byte_offset=1000,
        )
        session.add_all([memory_session, transcript, analysis_run])
        session.flush()

        rows = []
        for index, episode in enumerate(episodes):
            rows.append(
                Episode(
                    analysis_run=analysis_run,
                    session=memory_session,
                    transcript=transcript,
                    ordinal=index,
                    status=episode["episode_status"],
                    close_reason=episode["close_reason"],
                    byte_start=index * 100,
                    byte_end=(index + 1) * 100,
                    timestamp_start=episode["timestamp_end"],
                    timestamp_end=episode["timestamp_end"],
                    activity_count=1,
                    message_count=1,
                    tool_pair_count=0,
                ),
            )
        session.add_all(rows)
        session.flush()
        return analysis_run.id


def test_structurally_closed_episode_is_closed_regardless_of_age(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(
            database,
            (
                {
                    "episode_status": EPISODE_STATUS_CLOSED,
                    "close_reason": EPISODE_CLOSE_REASON_TIME_GAP,
                    "timestamp_end": BASE_TIME - timedelta(minutes=5),
                },
            ),
        )

        with database.session() as session:
            liveness = episode_liveness_for_analysis(
                session,
                analysis_run_id,
                as_of=BASE_TIME,
            )

        assert len(liveness) == 1
        assert liveness[0].status == EPISODE_LIVENESS_STATUS_CLOSED
        assert liveness[0].is_semantic_eligible
        assert liveness[0].age_seconds == 300
    finally:
        database.close_if_open()


def test_final_current_cursor_episode_is_live_before_idle_timeout(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(
            database,
            (
                {
                    "episode_status": EPISODE_STATUS_OPEN,
                    "close_reason": EPISODE_CLOSE_REASON_CURRENT_CURSOR,
                    "timestamp_end": BASE_TIME - timedelta(minutes=30),
                },
            ),
        )

        with database.session() as session:
            liveness = episode_liveness_for_analysis(
                session,
                analysis_run_id,
                as_of=BASE_TIME,
            )

        assert len(liveness) == 1
        assert liveness[0].status == EPISODE_LIVENESS_STATUS_LIVE
        assert not liveness[0].is_semantic_eligible
        assert liveness[0].age_seconds == 1800
    finally:
        database.close_if_open()


def test_final_current_cursor_episode_is_idle_eligible_at_timeout(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(
            database,
            (
                {
                    "episode_status": EPISODE_STATUS_OPEN,
                    "close_reason": EPISODE_CLOSE_REASON_CURRENT_CURSOR,
                    "timestamp_end": BASE_TIME - timedelta(hours=1),
                },
            ),
        )

        with database.session() as session:
            liveness = episode_liveness_for_analysis(
                session,
                analysis_run_id,
                as_of=BASE_TIME,
            )

        assert len(liveness) == 1
        assert liveness[0].status == EPISODE_LIVENESS_STATUS_IDLE_ELIGIBLE
        assert liveness[0].is_semantic_eligible
        assert liveness[0].age_seconds == 3600
    finally:
        database.close_if_open()


def test_current_cursor_without_timestamp_end_stays_live(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(
            database,
            (
                {
                    "episode_status": EPISODE_STATUS_OPEN,
                    "close_reason": EPISODE_CLOSE_REASON_CURRENT_CURSOR,
                    "timestamp_end": None,
                },
            ),
        )

        with database.session() as session:
            liveness = episode_liveness_for_analysis(
                session,
                analysis_run_id,
                as_of=BASE_TIME,
            )

        assert len(liveness) == 1
        assert liveness[0].status == EPISODE_LIVENESS_STATUS_LIVE
        assert liveness[0].age_seconds is None
        assert not liveness[0].is_semantic_eligible
    finally:
        database.close_if_open()


def test_only_final_current_cursor_episode_can_be_live(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(
            database,
            (
                {
                    "episode_status": EPISODE_STATUS_OPEN,
                    "close_reason": EPISODE_CLOSE_REASON_CURRENT_CURSOR,
                    "timestamp_end": BASE_TIME - timedelta(minutes=5),
                },
                {
                    "episode_status": EPISODE_STATUS_CLOSED,
                    "close_reason": EPISODE_CLOSE_REASON_TRANSCRIPT_END,
                    "timestamp_end": BASE_TIME - timedelta(minutes=4),
                },
            ),
        )

        with database.session() as session:
            liveness = episode_liveness_for_analysis(
                session,
                analysis_run_id,
                as_of=BASE_TIME,
            )

        assert [episode.status for episode in liveness] == [
            EPISODE_LIVENESS_STATUS_CLOSED,
            EPISODE_LIVENESS_STATUS_CLOSED,
        ]
        assert [episode.is_final for episode in liveness] == [False, True]
    finally:
        database.close_if_open()


def test_episode_liveness_for_analysis_returns_empty_tuple_without_episodes(tmp_path: Path) -> None:
    database = Database(sqlite_url(tmp_path / "memory.db"))
    database.initialize()
    try:
        analysis_run_id = create_analysis_with_episodes(database, ())

        with database.session() as session:
            assert episode_liveness_for_analysis(session, analysis_run_id, as_of=BASE_TIME) == ()
    finally:
        database.close_if_open()
