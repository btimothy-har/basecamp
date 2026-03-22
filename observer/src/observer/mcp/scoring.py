"""Scoring for hybrid search results.

Combines semantic similarity, keyword relevance, and time decay to rank
search entries.
"""

from __future__ import annotations

from datetime import UTC, datetime

from observer.constants import (
    SEARCH_KEYWORD_WEIGHT,
    SEARCH_SEMANTIC_WEIGHT,
    SEARCH_TIME_DECAY_POWER,
    SEARCH_TIME_DECAY_SCALE_DAYS,
)


def time_decay(
    timestamp: datetime,
    scale_days: float = SEARCH_TIME_DECAY_SCALE_DAYS,
    power: float = SEARCH_TIME_DECAY_POWER,
) -> float:
    """Power-law time decay returning a value in (0, 1].

    Returns 0.5 at exactly scale_days. Decays slowly toward 0 but never
    reaches it, so entries of any age remain differentiable by recency.

    Args:
        timestamp: Timestamp used for recency calculation (typically the artifact's last update time).
        scale_days: Age in days at which the decay factor equals 0.5.
        power: Exponent controlling decay rate; lower values decay more slowly.

    Returns:
        Decay factor in (0, 1].
    """
    now = datetime.now(UTC)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    age_days = max(0.0, (now - timestamp).total_seconds() / 86400)
    return 1.0 / (1.0 + (age_days / scale_days) ** power)


def compute_score(
    timestamp: datetime,
    *,
    semantic: float = 0.0,
    keyword: float = 0.0,
) -> float:
    """Hybrid relevance score blending semantic similarity, keyword match, and recency.

    Relevance is a weighted average of the two retrieval signals (60% semantic,
    40% keyword). A recency bonus (up to 20% of the final score) breaks ties
    in favour of recent entries without burying older ones.

    Either signal can be zero when the artifact was only found by one
    retriever — the weighted average naturally handles this.

    Args:
        timestamp: Timestamp used for recency calculation (typically the artifact's last update time).
        semantic: Cosine similarity in [0, 1] where 1 = identical. Pass
            ``1 - cosine_distance`` from pgvector.
        keyword: Normalized FTS rank in [0, 1] where 1 = strongest match
            in the batch.

    Returns:
        Score in [0, 1].
    """
    relevance = semantic * SEARCH_SEMANTIC_WEIGHT + keyword * SEARCH_KEYWORD_WEIGHT
    recency_bonus = time_decay(timestamp) * 0.2
    return min(1.0, relevance * 0.8 + recency_bonus)
