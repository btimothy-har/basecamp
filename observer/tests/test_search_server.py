"""Tests for observer.mcp.server module."""

from __future__ import annotations

from unittest.mock import patch

from observer.mcp.server import (
    _get_artifact,
    _get_transcript_summary,
    _search_artifacts,
    _search_transcripts,
)


class TestSearchArtifactsTool:
    def test_missing_project_name(self, monkeypatch):
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        result = _search_artifacts("test query")
        assert "error" in result

    def test_calls_engine(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

        mock_results = [{"source_id": 1, "type": "knowledge", "text": "found", "score": 0.9}]

        with patch("observer.mcp.engine.search_artifacts", return_value=mock_results) as mock:
            result = _search_artifacts("test query", top_k=5, threshold=0.5)

        mock.assert_called_once_with(
            "test query",
            "test-project",
            session_id=None,
            top_k=5,
            threshold=0.5,
            worktree=None,
        )
        assert result["count"] == 1
        assert result["results"] == mock_results

    def test_passes_session_id(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123")

        with patch("observer.mcp.engine.search_artifacts", return_value=[]) as mock:
            _search_artifacts("test query")

        assert mock.call_args.kwargs["session_id"] == "abc-123"

    def test_passes_worktree(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        with patch("observer.mcp.engine.search_artifacts", return_value=[]) as mock:
            _search_artifacts("test query", worktree="feature-branch")

        assert mock.call_args.kwargs["worktree"] == "feature-branch"


class TestSearchTranscriptsTool:
    def test_missing_project_name(self, monkeypatch):
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        result = _search_transcripts("test query")
        assert "error" in result

    def test_calls_engine(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)

        mock_results = [{"source_id": 1, "title": "Auth session", "text": "summary", "score": 0.8}]

        with patch("observer.mcp.engine.search_transcripts", return_value=mock_results) as mock:
            result = _search_transcripts("test query", top_k=5, threshold=0.5)

        mock.assert_called_once_with(
            "test query",
            "test-project",
            session_id=None,
            top_k=5,
            threshold=0.5,
            worktree=None,
        )
        assert result["count"] == 1
        assert result["results"] == mock_results

    def test_passes_session_id(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "abc-123")

        with patch("observer.mcp.engine.search_transcripts", return_value=[]) as mock:
            _search_transcripts("test query")

        assert mock.call_args.kwargs["session_id"] == "abc-123"

    def test_passes_worktree(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        with patch("observer.mcp.engine.search_transcripts", return_value=[]) as mock:
            _search_transcripts("test query", worktree="feature-branch")

        assert mock.call_args.kwargs["worktree"] == "feature-branch"


class TestGetArtifactTool:
    def test_found(self):
        mock_result = {"id": 1, "type": "knowledge", "text": "artifact text"}

        with patch("observer.mcp.engine.get_artifact", return_value=mock_result):
            result = _get_artifact(1)

        assert result["id"] == 1

    def test_not_found(self):
        with patch("observer.mcp.engine.get_artifact", return_value=None):
            result = _get_artifact(99999)

        assert "error" in result


class TestGetTranscriptSummaryTool:
    def test_found(self):
        mock_result = {"id": 1, "title": "Session title", "summary": "Summary text"}

        with patch("observer.mcp.engine.get_transcript_summary", return_value=mock_result):
            result = _get_transcript_summary(1)

        assert result["id"] == 1
        assert result["title"] == "Session title"

    def test_not_found(self):
        with patch("observer.mcp.engine.get_transcript_summary", return_value=None):
            result = _get_transcript_summary(99999)

        assert "error" in result
