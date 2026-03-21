"""Scoring and deduplication for semantic search results.

Combines cosine similarity with time decay to rank search entries by relevance
and recency. Post-retrieval dedup removes near-duplicate results.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from observer.constants import (
    SEARCH_DEDUP_SIMILARITY,
    SEARCH_TIME_DECAY_POWER,
    SEARCH_TIME_DECAY_SCALE_DAYS,
)

if TYPE_CHECKING:
    from typing import Any

# Dedup group for results without a section type (e.g. transcript summaries).
# All such results compete in one shared group.
_DEDUP_DEFAULT_GROUP = "__ungrouped__"


def time_decay(
    created_at: datetime,
    scale_days: float = SEARCH_TIME_DECAY_SCALE_DAYS,
    power: float = SEARCH_TIME_DECAY_POWER,
) -> float:
    """Power-law time decay returning a value in (0, 1].

    Returns 0.5 at exactly scale_days. Decays slowly toward 0 but never
    reaches it, so entries of any age remain differentiable by recency.

    Args:
        created_at: Creation timestamp of the entry.
        scale_days: Age in days at which the decay factor equals 0.5.
        power: Exponent controlling decay rate; lower values decay more slowly.

    Returns:
        Decay factor in (0, 1].
    """
    now = datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    age_days = max(0.0, (now - created_at).total_seconds() / 86400)
    return 1.0 / (1.0 + (age_days / scale_days) ** power)


def compute_score(cosine_distance: float, created_at: datetime) -> float:
    """Blended relevance score: similarity dominates, recency breaks ties.

    Similarity contributes 80% of the score; a recency bonus (up to 0.2)
    favours recent entries without burying older ones. This ensures a
    high-quality semantic match is always surfaced regardless of age.

    Args:
        cosine_distance: pgvector cosine distance in [0, 2] where 0 = identical.
        created_at: Creation timestamp of the entry.

    Returns:
        Score in [0, 1].
    """
    similarity = max(0.0, 1.0 - cosine_distance)
    recency_bonus = time_decay(created_at) * 0.2
    return min(1.0, similarity * 0.8 + recency_bonus)


def embedding_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two float embedding vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def deduplicate(
    results: list[dict[str, Any]],
    *,
    similarity_threshold: float = SEARCH_DEDUP_SIMILARITY,
) -> list[dict[str, Any]]:
    """Greedy pairwise dedup over score-descending results, scoped by type.

    Each search pathway calls this independently. For extractions, dedup
    groups by section type (two KNOWLEDGEs get deduped, but a KNOWLEDGE and
    DECISION survive). For transcripts, all results share one group.
    """
    kept: list[dict[str, Any]] = []
    kept_by_group: dict[str, list[list[float]]] = {}

    for result in results:
        embedding = result.get("_embedding")
        if embedding is None:
            kept.append(result)
            continue

        group = result.get("type", _DEDUP_DEFAULT_GROUP)
        group_embeddings = kept_by_group.get(group, [])

        is_duplicate = any(
            embedding_similarity(embedding, kept_emb) > similarity_threshold for kept_emb in group_embeddings
        )
        if not is_duplicate:
            kept.append(result)
            kept_by_group.setdefault(group, []).append(embedding)

    return kept
