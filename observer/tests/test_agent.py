"""Tests for the Claude CLI subprocess runner."""

import json
import subprocess
from unittest.mock import patch

import pytest
from observer.exceptions import ExtractionError
from observer.services.agent import Agent, AgentResponse


def _make_envelope(
    result: str = '{"summary": "test"}',
    cost_usd: float = 0.001,
    duration_ms: int = 500,
    session_id: str = "sess-123",
) -> str:
    return json.dumps(
        {
            "result": result,
            "cost_usd": cost_usd,
            "duration_ms": duration_ms,
            "session_id": session_id,
        }
    )


class TestAgentRun:
    def test_builds_command_correctly(self):
        agent = Agent(system_prompt="sys prompt")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(),
                stderr="",
            )
            agent.run("hello")

            args = mock_run.call_args
            cmd = args[0][0]
            assert cmd[0] == "claude"
            assert "-p" in cmd
            assert "--output-format" in cmd
            assert cmd[cmd.index("--output-format") + 1] == "json"
            assert "--model" in cmd
            assert cmd[cmd.index("--model") + 1] == "haiku"
            assert "--no-session-persistence" in cmd
            assert "--tools" in cmd
            assert cmd[cmd.index("--tools") + 1] == ""
            assert "--system-prompt" in cmd
            assert cmd[cmd.index("--system-prompt") + 1] == "sys prompt"
            assert "--setting-sources" in cmd
            assert cmd[cmd.index("--setting-sources") + 1] == ""
            assert "--strict-mcp-config" in cmd
            assert "--disable-slash-commands" in cmd
            assert "hello" not in cmd
            assert args[1]["input"] == "hello"

    def test_includes_json_schema_when_provided(self):
        agent = Agent(system_prompt="sys")
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(),
                stderr="",
            )
            agent.run("hello", json_schema=schema)

            cmd = mock_run.call_args[0][0]
            assert "--json-schema" in cmd
            schema_str = cmd[cmd.index("--json-schema") + 1]
            assert json.loads(schema_str) == schema

    def test_omits_json_schema_when_none(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(),
                stderr="",
            )
            agent.run("hello")

            cmd = mock_run.call_args[0][0]
            assert "--json-schema" not in cmd

    def test_parses_successful_response(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(
                    result="extracted data",
                    cost_usd=0.002,
                    duration_ms=750,
                    session_id="s-abc",
                ),
                stderr="",
            )
            resp = agent.run("hello")

        assert isinstance(resp, AgentResponse)
        assert resp.result == "extracted data"
        assert resp.cost_usd == 0.002
        assert resp.duration_ms == 750
        assert resp.session_id == "s-abc"

    def test_uses_custom_model(self):
        agent = Agent(system_prompt="sys", model="sonnet")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(),
                stderr="",
            )
            agent.run("hello")

            cmd = mock_run.call_args[0][0]
            assert cmd[cmd.index("--model") + 1] == "sonnet"


class TestAgentRunErrors:
    def test_raises_on_timeout(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=120)

            with pytest.raises(ExtractionError, match="timed out"):
                agent.run("hello")

    def test_raises_on_nonzero_exit(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="something went wrong",
            )

            with pytest.raises(ExtractionError, match="exited with code 1"):
                agent.run("hello")

    def test_raises_on_invalid_json(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="not json at all",
                stderr="",
            )

            with pytest.raises(ExtractionError, match="Failed to parse"):
                agent.run("hello")

    def test_raises_on_missing_result_key(self):
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"cost_usd": 0.001}),
                stderr="",
            )

            with pytest.raises(ExtractionError, match="Missing 'result'"):
                agent.run("hello")

    def test_defaults_optional_fields(self):
        """Response with only 'result' still parses with defaults."""
        agent = Agent(system_prompt="sys")

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps({"result": "ok"}),
                stderr="",
            )

            resp = agent.run("hello")
            assert resp.result == "ok"
            assert resp.cost_usd == 0.0
            assert resp.duration_ms == 0
            assert resp.session_id == ""

    def test_prefers_structured_output_over_result(self):
        """When structured_output is present, result should contain its JSON."""
        agent = Agent(system_prompt="sys")
        envelope = {
            "result": "some plain text the model also returned",
            "structured_output": {"summary": "the structured value"},
            "cost_usd": 0.001,
            "duration_ms": 500,
            "session_id": "sess-123",
        }

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=json.dumps(envelope),
                stderr="",
            )
            resp = agent.run("hello", json_schema={"type": "object"})

        assert json.loads(resp.result) == {"summary": "the structured value"}

    def test_passes_timeout_to_subprocess(self):
        agent = Agent(system_prompt="sys", timeout=30)

        with patch("observer.services.agent.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=_make_envelope(),
                stderr="",
            )
            agent.run("hello")

            assert mock_run.call_args[1]["timeout"] == 30
