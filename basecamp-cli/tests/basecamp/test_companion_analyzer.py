"""Tests for companion analyzer prompt and generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from basecamp.companion.analysis import COMPANION_ANALYSIS_VERSION, AnalysisSections, CompanionAnalysis
from basecamp.companion.analyzer import build_prompt, generate_analysis


def test_generate_analysis_with_injected_factory() -> None:
    fixed_now = datetime(2026, 6, 4, 12, 34, 56, tzinfo=UTC)

    @dataclass
    class FakeResult:
        output: AnalysisSections

    class FakeAgent:
        def run_sync(self, prompt: str) -> FakeResult:
            assert "SESSION CONTEXT (untrusted):" in prompt
            return FakeResult(output=AnalysisSections(recap=["r"], warnings=["w"]))

    def fake_agent_factory(model: str, *, output_type: type[AnalysisSections]) -> FakeAgent:
        assert model == "anthropic:claude-haiku-4-5"
        assert output_type is AnalysisSections
        return FakeAgent()

    result = generate_analysis(
        session_id="session-1",
        model="anthropic:claude-haiku-4-5",
        context="ctx",
        already_tracked="goal + tasks",
        prior=None,
        agent_factory=fake_agent_factory,
        now=fixed_now,
    )

    assert result.version == COMPANION_ANALYSIS_VERSION
    assert result.session_id == "session-1"
    assert result.model == "anthropic:claude-haiku-4-5"
    assert result.updated_at == fixed_now.isoformat()
    assert result.recap == ["r"]
    assert result.warnings == ["w"]


def test_build_prompt_with_prior_includes_prior_dashboard_block() -> None:
    prior = CompanionAnalysis(
        version=1,
        session_id="session-1",
        updated_at="2026-06-04T12:34:56+00:00",
        recap=["old recap"],
        decisions=["old decision"],
    )

    prompt = build_prompt(
        context="current session context",
        already_tracked="task A",
        prior=prior,
    )

    assert "ALREADY TRACKED" in prompt
    assert "task A" in prompt
    assert "PRIOR DASHBOARD" in prompt
    assert '"recap": ["old recap"]' in prompt
    assert '"decisions": ["old decision"]' in prompt
    assert "SESSION CONTEXT (untrusted):\ncurrent session context" in prompt
    assert "Produce the dashboard now." in prompt


def test_build_prompt_without_prior_omits_prior_dashboard_block() -> None:
    prompt = build_prompt(
        context="ctx",
        already_tracked="",
        prior=None,
    )

    assert "ALREADY TRACKED" in prompt
    assert "none" in prompt
    assert "PRIOR DASHBOARD" not in prompt
    assert "SESSION CONTEXT (untrusted):\nctx" in prompt
    assert "Produce the dashboard now." in prompt
