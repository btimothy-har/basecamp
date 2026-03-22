"""Tests for observer.mcp.server module."""

from __future__ import annotations

from unittest.mock import patch

from observer.mcp.server import (
    _get_artifact,
    _get_session,
    _get_transcript_detail,
    _resolve_project,
    _search_artifacts,
    _search_transcripts,
)


class TestResolveProject:
    def test_normal_mode(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "my-project")
        monkeypatch.delenv("BASECAMP_REFLECT", raising=False)
        assert _resolve_project() == "my-project"

    def test_missing_project_returns_error(self, monkeypatch):
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        monkeypatch.delenv("BASECAMP_REFLECT", raising=False)
        result = _resolve_project()
        assert isinstance(result, dict)
        assert "error" in result

    def test_reflect_mode_returns_none(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REFLECT", "1")
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        assert _resolve_project() is None

    def test_reflect_mode_overrides_project(self, monkeypatch):
        """Even when BASECAMP_REPO is set, reflect mode uses None for cross-project search."""
        monkeypatch.setenv("BASECAMP_REFLECT", "1")
        monkeypatch.setenv("BASECAMP_REPO", "my-project")
        assert _resolve_project() is None


class TestSearchArtifactsTool:
    def test_missing_project_name(self, monkeypatch):
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        monkeypatch.delenv("BASECAMP_REFLECT", raising=False)
        result = _search_artifacts("test query")
        assert "error" in result

    def test_calls_engine(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        mock_results = [{"artifact_id": 1, "type": "knowledge", "text": "found", "score": 0.9}]

        with patch("observer.mcp.engine.search_artifacts", return_value=mock_results) as mock:
            result = _search_artifacts("test query", top_k=5, threshold=0.5)

        mock.assert_called_once_with(
            "test query",
            "test-project",
            top_k=5,
            threshold=0.5,
            worktree=None,
        )
        assert result["count"] == 1
        assert result["results"] == mock_results

    def test_passes_worktree(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        with patch("observer.mcp.engine.search_artifacts", return_value=[]) as mock:
            _search_artifacts("test query", worktree="feature-branch")

        assert mock.call_args.kwargs["worktree"] == "feature-branch"

    def test_reflect_mode_passes_none_project(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REFLECT", "1")
        monkeypatch.delenv("BASECAMP_REPO", raising=False)

        with patch("observer.mcp.engine.search_artifacts", return_value=[]) as mock:
            result = _search_artifacts("test query")

        mock.assert_called_once()
        assert mock.call_args[0][1] is None
        assert "error" not in result


class TestSearchTranscriptsTool:
    def test_missing_project_name(self, monkeypatch):
        monkeypatch.delenv("BASECAMP_REPO", raising=False)
        monkeypatch.delenv("BASECAMP_REFLECT", raising=False)
        result = _search_transcripts("test query")
        assert "error" in result

    def test_calls_engine(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        mock_results = [{"artifact_id": 1, "title": "Auth session", "text": "summary", "score": 0.8}]

        with patch("observer.mcp.engine.search_transcripts", return_value=mock_results) as mock:
            result = _search_transcripts("test query", top_k=5, threshold=0.5)

        mock.assert_called_once_with(
            "test query",
            "test-project",
            top_k=5,
            threshold=0.5,
            worktree=None,
        )
        assert result["count"] == 1
        assert result["results"] == mock_results

    def test_passes_worktree(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REPO", "test-project")

        with patch("observer.mcp.engine.search_transcripts", return_value=[]) as mock:
            _search_transcripts("test query", worktree="feature-branch")

        assert mock.call_args.kwargs["worktree"] == "feature-branch"

    def test_reflect_mode_passes_none_project(self, monkeypatch):
        monkeypatch.setenv("BASECAMP_REFLECT", "1")
        monkeypatch.delenv("BASECAMP_REPO", raising=False)

        with patch("observer.mcp.engine.search_transcripts", return_value=[]) as mock:
            result = _search_transcripts("test query")

        mock.assert_called_once()
        assert mock.call_args[0][1] is None
        assert "error" not in result


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


class TestGetTranscriptDetailTool:
    def test_found(self):
        mock_result = {"id": 1, "title": "Session title", "summary": "Summary text"}

        with patch("observer.mcp.engine.get_transcript_detail", return_value=mock_result):
            result = _get_transcript_detail(1)

        assert result["id"] == 1
        assert result["title"] == "Session title"

    def test_not_found(self):
        with patch("observer.mcp.engine.get_transcript_detail", return_value=None):
            result = _get_transcript_detail(99999)

        assert "error" in result


class TestGetSessionTool:
    def test_found(self):
        mock_result = {
            "session_id": "sess-123",
            "started_at": "2025-01-15T10:00:00",
            "ended_at": None,
            "sections": {"summary": "test summary"},
        }

        with patch("observer.mcp.engine.get_session", return_value=mock_result):
            result = _get_session("sess-123")

        assert result["session_id"] == "sess-123"
        assert "sections" in result

    def test_not_found(self):
        with patch("observer.mcp.engine.get_session", return_value=None):
            result = _get_session("nonexistent")

        assert "error" in result
