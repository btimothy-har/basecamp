"""Tests for observer.search.scoring module."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from observer.constants import SEARCH_DEFAULT_THRESHOLD
from observer.search.scoring import compute_score, time_decay


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

    def test_ancient_entry_still_positive(self):
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
    """Tests for hybrid scoring: relevance = semantic*0.6 + keyword*0.4, score = relevance*0.8 + decay*0.2."""

    def test_perfect_dual_match_recent(self):
        # Both signals at 1.0 → relevance=1.0, score ≈ 1.0
        now = datetime.now(UTC)
        score = compute_score(now, semantic=1.0, keyword=1.0)
        assert score > 0.99

    def test_perfect_semantic_only_recent(self):
        # semantic=1.0, keyword=0 → relevance=0.6, score ≈ 0.68
        now = datetime.now(UTC)
        score = compute_score(now, semantic=1.0)
        assert 0.6 < score < 0.75

    def test_perfect_keyword_only_recent(self):
        # semantic=0, keyword=1.0 → relevance=0.4, score ≈ 0.52
        now = datetime.now(UTC)
        score = compute_score(now, keyword=1.0)
        assert 0.4 < score < 0.6

    def test_no_signals_scores_below_threshold(self):
        # Both signals at 0 → only recency bonus (≤0.2), below threshold.
        now = datetime.now(UTC)
        score = compute_score(now, semantic=0.0, keyword=0.0)
        assert score < SEARCH_DEFAULT_THRESHOLD

    def test_dual_match_beats_single(self):
        # An artifact matching on both signals should outscore one matching on just one.
        now = datetime.now(UTC)
        dual = compute_score(now, semantic=0.8, keyword=0.8)
        semantic_only = compute_score(now, semantic=0.8, keyword=0.0)
        keyword_only = compute_score(now, keyword=0.8, semantic=0.0)
        assert dual > semantic_only
        assert dual > keyword_only

    def test_semantic_weighted_higher_than_keyword(self):
        # At equal signal strength, semantic contributes more.
        now = datetime.now(UTC)
        semantic_only = compute_score(now, semantic=0.8, keyword=0.0)
        keyword_only = compute_score(now, semantic=0.0, keyword=0.8)
        assert semantic_only > keyword_only

    def test_high_similarity_old_artifact_above_threshold(self):
        now = datetime.now(UTC)
        score = compute_score(now - timedelta(days=30), semantic=0.9)
        assert score > SEARCH_DEFAULT_THRESHOLD

    def test_older_artifact_ranks_below_recent_at_same_signals(self):
        now = datetime.now(UTC)
        score_recent = compute_score(now - timedelta(days=1), semantic=0.8, keyword=0.5)
        score_old = compute_score(now - timedelta(days=180), semantic=0.8, keyword=0.5)
        assert score_recent > score_old

    def test_keyword_only_hit_above_threshold_when_strong(self):
        # A strong keyword match should surface even without semantic signal.
        now = datetime.now(UTC)
        score = compute_score(now, keyword=0.9)
        assert score > SEARCH_DEFAULT_THRESHOLD

    def test_score_capped_at_one(self):
        now = datetime.now(UTC)
        score = compute_score(now, semantic=1.0, keyword=1.0)
        assert score <= 1.0
