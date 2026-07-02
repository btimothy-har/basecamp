"""Tests for companion analyzer prompt and generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from companion_tui.analysis import COMPANION_ANALYSIS_VERSION, AnalysisSections, CompanionAnalysis
from companion_tui.analyzer import SYSTEM_PROMPT, build_prompt, generate_analysis


def test_system_prompt_describes_v2_advisory_sections() -> None:
    assert "UNTRUSTED DATA" in SYSTEM_PROMPT
    assert "Tool results and command outputs are intentionally omitted" in SYSTEM_PROMPT
    assert "monitor: ranked notes" in SYSTEM_PROMPT
    assert "needs_capture: preferences, decisions, or commitments" in SYSTEM_PROMPT
    assert "checkpoints: advisory verification points" in SYSTEM_PROMPT
    assert "not authoritative state" in SYSTEM_PROMPT


def test_generate_analysis_with_injected_factory() -> None:
    fixed_now = datetime(2026, 6, 4, 12, 34, 56, tzinfo=UTC)

    @dataclass
    class FakeResult:
        output: AnalysisSections

    class FakeAgent:
        def run_sync(self, prompt: str) -> FakeResult:
            assert "SESSION CONTEXT (untrusted):" in prompt
            return FakeResult(output=AnalysisSections(monitor=["m"], checkpoints=["c"]))

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
    assert result.monitor == ["m"]
    assert result.checkpoints == ["c"]


def test_build_prompt_with_prior_includes_prior_dashboard_block() -> None:
    prior = CompanionAnalysis(
        version=COMPANION_ANALYSIS_VERSION,
        session_id="session-1",
        updated_at="2026-06-04T12:34:56+00:00",
        monitor=["old monitor note"],
        checkpoints=["old checkpoint"],
    )

    prompt = build_prompt(
        context="current session context",
        already_tracked="task A",
        prior=prior,
    )

    assert "ALREADY TRACKED" in prompt
    assert "do not duplicate in monitor/needs_capture" in prompt
    assert "task A" in prompt
    assert "PRIOR DASHBOARD" in prompt
    assert '"monitor": ["old monitor note"]' in prompt
    assert '"checkpoints": ["old checkpoint"]' in prompt
    assert '"needsCapture"' in prompt
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
