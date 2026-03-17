"""FastMCP server exposing semantic search over observer memory.

Standalone stdio server — read-only DB consumer, independent of the daemon.
Logging goes to stderr to keep stdout clean for MCP protocol.
"""

from __future__ import annotations

import logging
import os
import sys

from fastmcp import FastMCP

from observer.constants import MCP_SERVER_INSTRUCTIONS, MCP_SERVER_NAME
from observer.mcp import engine

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)


def _is_reflect_mode() -> bool:
    return os.environ.get("BASECAMP_REFLECT") == "1"


def _resolve_search_context() -> tuple[str | None, str | None] | dict:
    """Resolve project and session for search, respecting reflect mode.

    Returns (project_name, session_id) on success, or an error dict.
    Reflect mode sets project_name to None for cross-project search.
    """
    project_name = os.environ.get("BASECAMP_REPO")
    session_id = os.environ.get("CLAUDE_SESSION_ID")
    if _is_reflect_mode():
        return None, session_id
    if not project_name:
        return {"error": "BASECAMP_REPO is not set"}
    return project_name, session_id


def _search_artifacts(
    query: str,
    top_k: int = 10,
    threshold: float = 0.3,
    worktree: str | None = None,
) -> dict:
    """Core search_artifacts logic, called by the MCP tool wrapper."""
    context = _resolve_search_context()
    if isinstance(context, dict):
        return context
    project_name, session_id = context

    results = engine.search_artifacts(
        query,
        project_name,
        session_id=session_id,
        top_k=top_k,
        threshold=threshold,
        worktree=worktree,
    )
    return {"results": results, "count": len(results)}


def _search_transcripts(
    query: str,
    top_k: int = 10,
    threshold: float = 0.3,
    worktree: str | None = None,
) -> dict:
    """Core search_transcripts logic, called by the MCP tool wrapper."""
    context = _resolve_search_context()
    if isinstance(context, dict):
        return context
    project_name, session_id = context

    results = engine.search_transcripts(
        query,
        project_name,
        session_id=session_id,
        top_k=top_k,
        threshold=threshold,
        worktree=worktree,
    )
    return {"results": results, "count": len(results)}


def _get_artifact(artifact_id: int) -> dict:
    """Core get_artifact logic, called by the MCP tool wrapper."""
    result = engine.get_artifact(artifact_id)
    if result is None:
        return {"error": f"Artifact {artifact_id} not found"}
    return result


def _get_transcript_summary(transcript_id: int) -> dict:
    """Core get_transcript_summary logic, called by the MCP tool wrapper."""
    result = engine.get_transcript_summary(transcript_id)
    if result is None:
        return {"error": f"Transcript {transcript_id} not found"}
    return result


@mcp.tool
def search_artifacts(
    query: str,
    top_k: int = 10,
    threshold: float = 0.3,
    worktree: str | None = None,
) -> dict:
    """Search for extracted knowledge, decisions, actions, and constraints.

    Precision retrieval over artifact entries with session context expansion.
    Each result includes sibling artifacts from the same transcript. Use
    get_artifact to retrieve full details for any result or sibling.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 10).
        threshold: Minimum relevance score in [0, 1] (default 0.3).
        worktree: Optional worktree label to filter by.

    Returns:
        Dict with 'results' list and 'count'. Each result contains source_id,
        type, text, score, created_at, transcript_id, and session_context
        (list of {id, type} sibling artifacts from the same transcript).
        Use get_artifact to retrieve full details including the prompt that
        triggered extraction.
    """
    return _search_artifacts(query, top_k=top_k, threshold=threshold, worktree=worktree)


@mcp.tool
def search_transcripts(
    query: str,
    top_k: int = 10,
    threshold: float = 0.3,
    worktree: str | None = None,
) -> dict:
    """Search for relevant past sessions by their summaries.

    Orientation retrieval — finds sessions whose work is semantically related
    to the query. Use get_transcript_summary to drill down into the full
    structured summary (goal, active context, key decisions, constraints).

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 10).
        threshold: Minimum relevance score in [0, 1] (default 0.3).
        worktree: Optional worktree label to filter by.

    Returns:
        Dict with 'results' list and 'count'. Each result contains source_id,
        title, text, score, created_at, and transcript_id.
    """
    return _search_transcripts(query, top_k=top_k, threshold=threshold, worktree=worktree)


@mcp.tool
def get_artifact(artifact_id: int) -> dict:
    """Retrieve a single artifact by ID with full details.

    Returns artifact details including the prompt text that triggered
    extraction (prompted_by field).

    Args:
        artifact_id: The artifact's database ID.

    Returns:
        Dict with artifact details including prompted_by, or error if
        not found.
    """
    return _get_artifact(artifact_id)


@mcp.tool
def get_transcript_summary(transcript_id: int) -> dict:
    """Retrieve a transcript's summary and metadata.

    Returns the full summary, title, session timing, and session ID
    for a transcript. Use this to drill down on transcript summary
    hits from search results.

    Args:
        transcript_id: The transcript's database ID.

    Returns:
        Dict with transcript details, or error if not found.
    """
    return _get_transcript_summary(transcript_id)


def _get_session(session_id: str) -> dict:
    """Core get_session logic, called by the MCP tool wrapper."""
    result = engine.get_session(session_id)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


@mcp.tool
def get_session(session_id: str) -> dict:
    """Retrieve a session's transcript and recent artifacts by session ID.

    Look up a worker session by its Claude session ID to check its current
    state, see what it has accomplished (title, summary), and review its
    most recent extracted artifacts.

    Args:
        session_id: The Claude session ID (from CLAUDE_SESSION_ID).

    Returns:
        Dict with session_id, title, summary, started_at, ended_at,
        and recent_artifacts (up to 5 most recent), or error if not found.
    """
    return _get_session(session_id)


def main() -> None:
    """Entry point for the observer-search MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
