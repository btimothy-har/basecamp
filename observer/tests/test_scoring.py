"""Tests for observer.mcp.scoring module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from observer.constants import EMBEDDING_DIMENSIONS, SEARCH_DEFAULT_THRESHOLD
from observer.mcp.scoring import compute_score, deduplicate, time_decay


class TestTimeDecay:
    def test_returns_one_half_at_scale_days(self):
        now = datetime.now(UTC)
        at_scale = now - timedelta(days=30)
        result = time_decay(at_scale, scale_days=30.0)
        assert abs(result - 0.5) < 0.01

    def test_recent_artifact_scores_near_one(self):
        now = datetime.now(UTC)
        result = time_decay(now, scale_days=30.0)
        assert result > 0.99

    def test_old_artifact_scores_below_half(self):
        now = datetime.now(UTC)
        old = now - timedelta(days=60)
        result = time_decay(old, scale_days=30.0)
        assert result < 0.5

    def test_ancient_artifact_still_positive(self):
        # Power-law decay never reaches zero — old artifacts remain differentiable.
        now = datetime.now(UTC)
        ancient = now - timedelta(days=730)
        result = time_decay(ancient, scale_days=30.0)
        assert result > 0.0

    def test_recency_differentiates_30_and_180_days(self):
        # 30-day-old and 180-day-old artifacts should have meaningfully different decay.
        now = datetime.now(UTC)
        decay_30 = time_decay(now - timedelta(days=30), scale_days=30.0)
        decay_180 = time_decay(now - timedelta(days=180), scale_days=30.0)
        assert decay_30 > decay_180
        assert decay_30 - decay_180 > 0.1  # not a rounding-error difference

    def test_naive_datetime_treated_as_utc(self):
        now = datetime.now(UTC)
        naive = now.replace(tzinfo=None)
        result = time_decay(naive, scale_days=30.0)
        assert result > 0.99


class TestComputeScore:
    def test_perfect_match_recent(self):
        now = datetime.now(UTC)
        score = compute_score(0.0, now)
        assert score > 0.99

    def test_distant_match_scores_low(self):
        now = datetime.now(UTC)
        score = compute_score(1.5, now)
        assert score < 0.5

    def test_zero_similarity_scores_below_threshold(self):
        # Orthogonal vectors (cosine_distance=1.0) get only the recency bonus (≤0.2),
        # which is always below the search threshold of 0.3.
        now = datetime.now(UTC)
        score = compute_score(1.0, now)
        assert score < SEARCH_DEFAULT_THRESHOLD

    def test_negative_similarity_treated_as_zero(self):
        # Anti-correlated vectors (cosine_distance=2.0) clamp to similarity=0.
        now = datetime.now(UTC)
        score = compute_score(2.0, now)
        assert score < SEARCH_DEFAULT_THRESHOLD

    def test_high_similarity_old_artifact_above_threshold_30d(self):
        # Acceptance criterion: cd=0.1 at 30 days must exceed the search threshold.
        now = datetime.now(UTC)
        score = compute_score(0.1, now - timedelta(days=30))
        assert score > SEARCH_DEFAULT_THRESHOLD

    def test_high_similarity_old_artifact_above_threshold_180d(self):
        # Acceptance criterion: cd=0.1 at 180 days must still exceed 0.7.
        now = datetime.now(UTC)
        score = compute_score(0.1, now - timedelta(days=180))
        assert score > 0.7

    def test_older_artifact_ranks_below_recent_at_same_similarity(self):
        # Recency bonus should meaningfully differentiate same-quality artifacts.
        now = datetime.now(UTC)
        score_recent = compute_score(0.1, now - timedelta(days=1))
        score_old = compute_score(0.1, now - timedelta(days=180))
        assert score_recent > score_old


def _make_embedding(index: int) -> list[float]:
    """Create an embedding with energy concentrated at a specific dimension.

    Different indices produce near-orthogonal vectors (low cosine similarity).
    """
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[index % EMBEDDING_DIMENSIONS] = 1.0
    return values


class TestDeduplicate:
    def test_empty_input(self):
        assert deduplicate([]) == []

    def test_distinct_results_kept(self):
        results = [
            {"id": 1, "type": "KNOWLEDGE", "score": 0.9, "_embedding": _make_embedding(0)},
            {"id": 2, "type": "KNOWLEDGE", "score": 0.8, "_embedding": _make_embedding(1)},
        ]
        kept = deduplicate(results)
        assert len(kept) == 2

    def test_identical_embeddings_deduped_within_same_type(self):
        emb = _make_embedding(0)
        results = [
            {"id": 1, "type": "KNOWLEDGE", "score": 0.9, "_embedding": emb},
            {"id": 2, "type": "KNOWLEDGE", "score": 0.8, "_embedding": emb},
        ]
        kept = deduplicate(results)
        assert len(kept) == 1
        assert kept[0]["id"] == 1

    def test_similar_embeddings_kept_across_types(self):
        """A CONSTRAINT and DECISION with identical embeddings both survive."""
        emb = _make_embedding(0)
        results = [
            {"id": 1, "type": "DECISION", "score": 0.9, "_embedding": emb},
            {"id": 2, "type": "CONSTRAINT", "score": 0.8, "_embedding": emb},
        ]
        kept = deduplicate(results)
        assert len(kept) == 2

    def test_results_without_embedding_always_kept(self):
        results = [
            {"id": 1, "score": 0.9},
            {"id": 2, "score": 0.8},
        ]
        kept = deduplicate(results)
        assert len(kept) == 2

    def test_identical_summaries_deduped(self):
        """Two near-identical transcript summaries (no type field) get deduped."""
        emb = _make_embedding(0)
        results = [
            {"source_id": 1, "score": 0.9, "_embedding": emb},
            {"source_id": 2, "score": 0.8, "_embedding": emb},
        ]
        kept = deduplicate(results)
        assert len(kept) == 1
        assert kept[0]["source_id"] == 1
