"""Tests for the recall CLI (observer.cli.recall)."""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner
from observer.cli.recall import main
from observer.data.enums import SectionType

# Engine is imported lazily inside function bodies, so we patch at the source module.
_ENGINE = "observer.mcp.engine"


def _invoke(args: list[str], *, env: dict[str, str] | None = None):
    """Run a recall CLI command and return parsed JSON + exit code."""
    runner = CliRunner(env=env)
    result = runner.invoke(main, args)
    output = json.loads(result.output) if result.output.strip() else None
    return output, result.exit_code


class TestSearch:
    """Tests for `recall search <query>`."""

    def test_summary_search_calls_search_transcripts(self):
        mock_results = [{"session_id": "s1", "text": "summary", "score": 0.8, "title": "Title"}]

        with patch(f"{_ENGINE}.search_transcripts", return_value=mock_results) as mock_fn:
            output, code = _invoke(
                ["search", "test query"],
                env={"BASECAMP_REPO": "my-project", "CLAUDE_SESSION_ID": "current"},
            )

        assert code == 0
        assert output["count"] == 1
        assert output["results"][0]["type"] == "summary"
        mock_fn.assert_called_once_with(
            "test query",
            "my-project",
            top_k=10,
            threshold=0.3,
            session_id="current",
        )

    def test_artifact_search_calls_search_artifacts(self):
        mock_results = [
            {"session_id": "s1", "text": "fact", "score": 0.9, "type": SectionType.KNOWLEDGE.value},
        ]

        with patch(f"{_ENGINE}.search_artifacts", return_value=mock_results) as mock_fn:
            output, code = _invoke(["search", "test query", "--type", "knowledge"])

        assert code == 0
        assert output["count"] == 1
        assert output["results"][0]["type"] == SectionType.KNOWLEDGE.value
        assert mock_fn.call_args[1]["section_types"] == ["knowledge"]

    def test_artifact_search_passes_section_types_to_engine(self):
        # Engine is responsible for type filtering; CLI passes section_types kwarg.
        mock_results = [
            {"session_id": "s1", "text": "fact", "score": 0.9, "type": "knowledge"},
            {"session_id": "s3", "text": "rule", "score": 0.6, "type": "constraints"},
        ]

        with patch(f"{_ENGINE}.search_artifacts", return_value=mock_results) as mock_fn:
            output, code = _invoke(["search", "test query", "--type", "knowledge,constraints"])

        assert code == 0
        assert output["count"] == 2
        assert mock_fn.call_args[1]["section_types"] == ["knowledge", "constraints"]

    def test_invalid_type_returns_error(self):
        output, code = _invoke(["search", "test query", "--type", "bogus"])

        assert code == 1
        assert "error" in output
        assert "bogus" in output["error"]

    def test_cross_project_ignores_basecamp_repo(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--cross-project"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[0][1] is None

    def test_no_basecamp_repo_passes_none(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(["search", "test query"])

        assert mock_fn.call_args[0][1] is None

    def test_session_id_forwarded_from_env(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query"],
                env={"CLAUDE_SESSION_ID": "sess-abc"},
            )

        assert mock_fn.call_args[1]["session_id"] == "sess-abc"

    def test_no_session_id_passes_none(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(["search", "test query"])

        assert mock_fn.call_args[1]["session_id"] is None

    def test_custom_top_k_and_threshold(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(["search", "test query", "--top-k", "5", "--threshold", "0.7"])

        assert mock_fn.call_args[1]["top_k"] == 5
        assert mock_fn.call_args[1]["threshold"] == 0.7

    def test_engine_exception_returns_json_error(self):
        with patch(f"{_ENGINE}.search_transcripts", side_effect=RuntimeError("db down")):
            output, code = _invoke(["search", "test query"])

        assert code == 1
        assert "Search failed" in output["error"]


class TestSession:
    """Tests for `recall session <id>`."""

    def test_returns_session_data(self):
        mock_session = {
            "session_id": "sess-123",
            "started_at": "2026-03-20T10:00:00",
            "ended_at": None,
            "sections": {"summary": "Did stuff"},
        }

        with patch(f"{_ENGINE}.get_session", return_value=mock_session) as mock_fn:
            output, code = _invoke(["session", "sess-123"])

        assert code == 0
        assert output["session_id"] == "sess-123"
        mock_fn.assert_called_once_with("sess-123")

    def test_not_found_returns_error(self):
        with patch(f"{_ENGINE}.get_session", return_value=None):
            output, code = _invoke(["session", "nonexistent"])

        assert code == 1
        assert "not found" in output["error"].lower()

    def test_engine_exception_returns_json_error(self):
        with patch(f"{_ENGINE}.get_session", side_effect=RuntimeError("db down")):
            output, code = _invoke(["session", "bad-id"])

        assert code == 1
        assert "Session lookup failed" in output["error"]


class TestCLIRouting:
    """Tests for top-level CLI behavior."""

    def test_bare_recall_shows_help(self):
        runner = CliRunner()
        result = runner.invoke(main, [])
        # Click group without invoke_without_command shows usage + exit 2
        assert "search" in result.output
        assert "session" in result.output

    def test_missing_query_shows_error(self):
        runner = CliRunner()
        result = runner.invoke(main, ["search"])
        assert result.exit_code != 0
