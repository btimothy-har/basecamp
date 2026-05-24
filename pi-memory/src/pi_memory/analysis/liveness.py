"""Episode liveness eligibility read model."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from pi_memory.constants import EPISODE_CLOSE_REASON_CURRENT_CURSOR
from pi_memory.db.models import Episode

EPISODE_LIVENESS_STATUS_LIVE = "live"
EPISODE_LIVENESS_STATUS_IDLE_ELIGIBLE = "idle_eligible"
EPISODE_LIVENESS_STATUS_CLOSED = "closed"
DEFAULT_EPISODE_IDLE_TIMEOUT = timedelta(hours=1)

EpisodeLivenessStatus = Literal["live", "idle_eligible", "closed"]


@dataclass(frozen=True)
class EpisodeLiveness:
    episode_id: int
    analysis_run_id: int
    session_id: int
    transcript_id: int
    ordinal: int
    status: EpisodeLivenessStatus
    close_reason: str | None
    first_entry_id: int | None
    last_entry_id: int | None
    byte_start: int
    byte_end: int
    timestamp_end: datetime | None
    as_of: datetime
    age_seconds: float | None
    is_final: bool
    idle_timeout_seconds: float

    @property
    def is_semantic_eligible(self) -> bool:
        return self.status != EPISODE_LIVENESS_STATUS_LIVE


def episode_liveness_for_analysis(
    session: Session,
    analysis_run_id: int,
    *,
    as_of: datetime,
    idle_timeout: timedelta = DEFAULT_EPISODE_IDLE_TIMEOUT,
) -> tuple[EpisodeLiveness, ...]:
    episodes = tuple(
        session.scalars(
            select(Episode)
            .where(Episode.analysis_run_id == analysis_run_id)
            .order_by(Episode.ordinal.asc(), Episode.id.asc()),
        ).all(),
    )
    return episode_liveness_for_episodes(
        episodes,
        as_of=as_of,
        idle_timeout=idle_timeout,
    )


def episode_liveness_for_episodes(
    episodes: Sequence[Episode],
    *,
    as_of: datetime,
    idle_timeout: timedelta = DEFAULT_EPISODE_IDLE_TIMEOUT,
) -> tuple[EpisodeLiveness, ...]:
    if not episodes:
        return ()

    final_ordinal = max(episode.ordinal for episode in episodes)
    return tuple(
        evaluate_episode_liveness(
            episode,
            as_of=as_of,
            final_ordinal=final_ordinal,
            idle_timeout=idle_timeout,
        )
        for episode in episodes
    )


def evaluate_episode_liveness(
    episode: Episode,
    *,
    as_of: datetime,
    final_ordinal: int,
    idle_timeout: timedelta = DEFAULT_EPISODE_IDLE_TIMEOUT,
) -> EpisodeLiveness:
    normalized_as_of = _as_utc(as_of)
    timestamp_end = _as_utc(episode.timestamp_end) if episode.timestamp_end is not None else None
    is_final = episode.ordinal == final_ordinal
    age_seconds = _age_seconds(timestamp_end, normalized_as_of)
    status = _status(
        close_reason=episode.close_reason,
        is_final=is_final,
        age_seconds=age_seconds,
        idle_timeout=idle_timeout,
    )

    return EpisodeLiveness(
        episode_id=episode.id,
        analysis_run_id=episode.analysis_run_id,
        session_id=episode.session_id,
        transcript_id=episode.transcript_id,
        ordinal=episode.ordinal,
        status=status,
        close_reason=episode.close_reason,
        first_entry_id=episode.first_entry_id,
        last_entry_id=episode.last_entry_id,
        byte_start=episode.byte_start,
        byte_end=episode.byte_end,
        timestamp_end=timestamp_end,
        as_of=normalized_as_of,
        age_seconds=age_seconds,
        is_final=is_final,
        idle_timeout_seconds=idle_timeout.total_seconds(),
    )


def _status(
    *,
    close_reason: str | None,
    is_final: bool,
    age_seconds: float | None,
    idle_timeout: timedelta,
) -> EpisodeLivenessStatus:
    if close_reason != EPISODE_CLOSE_REASON_CURRENT_CURSOR or not is_final:
        return EPISODE_LIVENESS_STATUS_CLOSED
    if age_seconds is None:
        return EPISODE_LIVENESS_STATUS_LIVE
    if age_seconds >= idle_timeout.total_seconds():
        return EPISODE_LIVENESS_STATUS_IDLE_ELIGIBLE
    return EPISODE_LIVENESS_STATUS_LIVE


def _age_seconds(timestamp_end: datetime | None, as_of: datetime) -> float | None:
    if timestamp_end is None:
        return None
    return (as_of - timestamp_end).total_seconds()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
