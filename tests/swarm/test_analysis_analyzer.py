"""Tests for the provisional PydanticAI analyzer (seam wiring, no network)."""

from __future__ import annotations

from typing import Any

import pytest

from basecamp.swarm.analysis.analyzer import PydanticAIAnalyzer
from basecamp.swarm.analysis.sections import AnalysisSections


class _FakeResult:
    def __init__(self, output: Any) -> None:
        self.output = output


class _FakeAgent:
    def __init__(self, output: Any, capture: dict[str, Any]) -> None:
        self._output = output
        self._capture = capture

    def run_sync(self, prompt: str) -> _FakeResult:
        self._capture["prompt"] = prompt
        return _FakeResult(self._output)


def _factory(output: Any, capture: dict[str, Any]):
    def make(model: str, *, output_type: type[Any]) -> _FakeAgent:
        capture["model"] = model
        capture["output_type"] = output_type
        return _FakeAgent(output, capture)

    return make


@pytest.mark.asyncio
async def test_builds_prompt_and_returns_sections() -> None:
    capture: dict[str, Any] = {}
    sections = AnalysisSections(monitor=["m1"], needs_capture=["n1"], checkpoints=[])
    analyzer = PydanticAIAnalyzer(agent_factory=_factory(sections, capture))

    result = await analyzer.analyze(context="CTX", already_tracked="goal: ship it", prior=None, model="prov/model")

    assert result is sections
    assert capture["model"] == "prov/model"
    assert capture["output_type"] is AnalysisSections
    assert "SESSION CONTEXT (untrusted):\nCTX" in capture["prompt"]
    assert "goal: ship it" in capture["prompt"]
    assert "PRIOR DASHBOARD" not in capture["prompt"]


@pytest.mark.asyncio
async def test_prior_dashboard_is_carried_into_the_prompt() -> None:
    capture: dict[str, Any] = {}
    prior = AnalysisSections(monitor=["kept item"], needs_capture=[], checkpoints=[])
    analyzer = PydanticAIAnalyzer(agent_factory=_factory(AnalysisSections(), capture))

    await analyzer.analyze(context="C", already_tracked="", prior=prior, model="m")

    assert "PRIOR DASHBOARD" in capture["prompt"]
    assert "kept item" in capture["prompt"]
    assert "needsCapture" in capture["prompt"]  # serialized by alias (camelCase)


@pytest.mark.asyncio
async def test_dict_output_is_validated_into_sections() -> None:
    capture: dict[str, Any] = {}
    raw = {"monitor": ["x"], "needsCapture": ["y"], "checkpoints": []}
    analyzer = PydanticAIAnalyzer(agent_factory=_factory(raw, capture))

    result = await analyzer.analyze(context="C", already_tracked="", prior=None, model="m")

    assert isinstance(result, AnalysisSections)
    assert result.monitor == ["x"]
    assert result.needs_capture == ["y"]


@pytest.mark.asyncio
async def test_close_is_idempotent_and_pool_recreates_on_next_run() -> None:
    capture: dict[str, Any] = {}
    analyzer = PydanticAIAnalyzer(agent_factory=_factory(AnalysisSections(monitor=["a"]), capture))

    await analyzer.analyze(context="C", already_tracked="", prior=None, model="m")
    analyzer.close()
    analyzer.close()  # idempotent — no error on a second close

    result = await analyzer.analyze(context="C", already_tracked="", prior=None, model="m")
    assert result.monitor == ["a"]  # executor lazily recreated after close
    analyzer.close()
