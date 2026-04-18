"""Tests for the recall CLI (observer.cli.recall)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

from click.testing import CliRunner
from observer.cli.recall import main
from observer.data.enums import SectionType

# Engine is imported lazily inside function bodies, so we patch at the source module.
_ENGINE = "observer.search"


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
            after=None,
            before=None,
        )

    def test_artifact_search_calls_search_artifacts(self):
        mock_results = [
            {"session_id": "s1", "text": "fact", "score": 0.9, "type": SectionType.KNOWLEDGE.value},
        ]

        with patch(f"{_ENGINE}.search_artifacts", return_value=mock_results) as mock_fn:
            output, code = _invoke(
                ["search", "test query", "--type", "knowledge"],
                env={"BASECAMP_REPO": "my-project"},
            )

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
            output, code = _invoke(
                ["search", "test query", "--type", "knowledge,constraints"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert code == 0
        assert output["count"] == 2
        assert mock_fn.call_args[1]["section_types"] == ["knowledge", "constraints"]

    def test_invalid_type_returns_error(self):
        output, code = _invoke(
            ["search", "test query", "--type", "bogus"],
            env={"BASECAMP_REPO": "my-project"},
        )

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

    def test_no_basecamp_repo_errors_when_not_cross_project(self):
        output, code = _invoke(["search", "test query"])

        assert code == 1
        assert "BASECAMP_REPO" in output["error"]

    def test_session_id_forwarded_from_env(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query"],
                env={"BASECAMP_REPO": "my-project", "CLAUDE_SESSION_ID": "sess-abc"},
            )

        assert mock_fn.call_args[1]["session_id"] == "sess-abc"

    def test_no_session_id_passes_none(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["session_id"] is None

    def test_custom_top_k_and_threshold(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--top-k", "5", "--threshold", "0.7"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["top_k"] == 5
        assert mock_fn.call_args[1]["threshold"] == 0.7

    def test_engine_exception_returns_json_error(self):
        with patch(f"{_ENGINE}.search_transcripts", side_effect=RuntimeError("db down")):
            output, code = _invoke(
                ["search", "test query"],
                env={"BASECAMP_REPO": "my-project"},
            )

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

    def test_list_appears_in_help(self):
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert "list" in result.output


class TestSearchDateFilters:
    """Tests for --after/--before on `recall search`."""

    def test_after_forwarded_to_search_transcripts(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--after", "2026-03-01"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["after"] == datetime(2026, 3, 1, tzinfo=UTC)

    def test_before_forwarded_to_search_transcripts(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--before", "2026-03-15"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["before"] == datetime(2026, 3, 15, tzinfo=UTC)

    def test_date_range_forwarded_to_search_artifacts(self):
        with patch(f"{_ENGINE}.search_artifacts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--type", "knowledge", "--after", "2026-01-01", "--before", "2026-02-01"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["after"] == datetime(2026, 1, 1, tzinfo=UTC)
        assert mock_fn.call_args[1]["before"] == datetime(2026, 2, 1, tzinfo=UTC)

    def test_iso_datetime_parsed(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query", "--after", "2026-03-01T14:30:00"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["after"] == datetime(2026, 3, 1, 14, 30, tzinfo=UTC)

    def test_invalid_date_returns_error(self):
        runner = CliRunner(env={"BASECAMP_REPO": "my-project"})
        result = runner.invoke(main, ["search", "test query", "--after", "not-a-date"])

        assert result.exit_code != 0
        assert "Invalid date" in result.output

    def test_no_dates_passes_none(self):
        with patch(f"{_ENGINE}.search_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["search", "test query"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["after"] is None
        assert mock_fn.call_args[1]["before"] is None


class TestList:
    """Tests for `recall list`."""

    def test_no_type_calls_list_transcripts(self):
        mock_results = [{"session_id": "s1", "text": "summary", "started_at": "2026-03-01T00:00:00"}]

        with patch(f"{_ENGINE}.list_transcripts", return_value=mock_results) as mock_fn:
            output, code = _invoke(
                ["list"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert code == 0
        assert output["count"] == 1
        mock_fn.assert_called_once_with(
            "my-project",
            after=None,
            before=None,
            top_k=10,
        )

    def test_type_calls_list_artifacts(self):
        mock_results = [{"session_id": "s1", "text": "fact", "type": "knowledge"}]

        with patch(f"{_ENGINE}.list_artifacts", return_value=mock_results) as mock_fn:
            output, code = _invoke(
                ["list", "--type", "knowledge"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert code == 0
        assert output["count"] == 1
        assert mock_fn.call_args[1]["section_types"] == ["knowledge"]

    def test_session_calls_list_artifacts(self):
        with patch(f"{_ENGINE}.list_artifacts", return_value=[]) as mock_fn:
            _invoke(
                ["list", "--session", "sess-123"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["session_id"] == "sess-123"

    def test_after_and_before_forwarded(self):
        with patch(f"{_ENGINE}.list_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["list", "--after", "2026-03-01", "--before", "2026-03-15"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["after"] == datetime(2026, 3, 1, tzinfo=UTC)
        assert mock_fn.call_args[1]["before"] == datetime(2026, 3, 15, tzinfo=UTC)

    def test_cross_project_passes_none(self):
        with patch(f"{_ENGINE}.list_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["list", "--cross-project"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[0][0] is None

    def test_no_basecamp_repo_errors(self):
        output, code = _invoke(["list"])

        assert code == 1
        assert "BASECAMP_REPO" in output["error"]

    def test_invalid_type_returns_error(self):
        output, code = _invoke(
            ["list", "--type", "bogus"],
            env={"BASECAMP_REPO": "my-project"},
        )

        assert code == 1
        assert "bogus" in output["error"]

    def test_custom_top_k(self):
        with patch(f"{_ENGINE}.list_transcripts", return_value=[]) as mock_fn:
            _invoke(
                ["list", "--top-k", "5"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert mock_fn.call_args[1]["top_k"] == 5

    def test_engine_exception_returns_json_error(self):
        with patch(f"{_ENGINE}.list_transcripts", side_effect=RuntimeError("db down")):
            output, code = _invoke(
                ["list"],
                env={"BASECAMP_REPO": "my-project"},
            )

        assert code == 1
        assert "List failed" in output["error"]
