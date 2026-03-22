"""FastMCP server exposing semantic search over observer memory.

Standalone stdio server — read-only DB consumer.
Logging goes to stderr to keep stdout clean for MCP protocol.
"""

from __future__ import annotations

import logging
import os
import sys

from fastmcp import FastMCP

from observer.constants import MCP_SERVER_INSTRUCTIONS, MCP_SERVER_NAME
from observer.mcp import engine
from observer.services.config import get_mode

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP(MCP_SERVER_NAME, instructions=MCP_SERVER_INSTRUCTIONS)


def _is_reflect_mode() -> bool:
    return os.environ.get("BASECAMP_REFLECT") == "1"


def _resolve_project() -> str | None | dict:
    """Resolve project name for search, respecting reflect mode.

    Returns project_name on success (None in reflect mode), or an error dict.
    """
    if _is_reflect_mode():
        return None
    project_name = os.environ.get("BASECAMP_REPO")
    if not project_name:
        return {"error": "BASECAMP_REPO is not set"}
    return project_name


_MODE_DISABLED_MSG = "Observer is off. No extraction data is available."


def _search_artifacts(
    query: str,
    top_k: int = 10,
    threshold: float = 0.3,
    worktree: str | None = None,
) -> dict:
    """Core search_artifacts logic, called by the MCP tool wrapper."""
    if get_mode() == "off":
        return {"error": _MODE_DISABLED_MSG}

    project = _resolve_project()
    if isinstance(project, dict):
        return project

    results = engine.search_artifacts(
        query,
        project,
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
    project = _resolve_project()
    if isinstance(project, dict):
        return project

    results = engine.search_transcripts(
        query,
        project,
        top_k=top_k,
        threshold=threshold,
        worktree=worktree,
    )
    return {"results": results, "count": len(results)}


def _get_artifact(artifact_id: int) -> dict:
    """Core get_artifact logic, called by the MCP tool wrapper."""
    if get_mode() == "off":
        return {"error": _MODE_DISABLED_MSG}

    result = engine.get_artifact(artifact_id)
    if result is None:
        return {"error": f"Artifact {artifact_id} not found"}
    return result


def _get_transcript_detail(transcript_id: int) -> dict:
    """Core get_transcript_detail logic, called by the MCP tool wrapper."""
    result = engine.get_transcript_detail(transcript_id)
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

    Precision retrieval over transcript artifact sections. Each result
    is a specific artifact (knowledge, decision, constraint, or action)
    from a past session. Use get_artifact to retrieve full details.

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 10).
        threshold: Minimum relevance score in [0, 1] (default 0.3).
        worktree: Optional worktree label to filter by.

    Returns:
        Dict with 'results' list and 'count'. Each result contains session_id,
        type (section_type), text, score, and created_at.
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
    to the query. Use get_transcript_detail to drill down into the full
    structured sections (summary, knowledge, decisions, constraints, actions).

    Args:
        query: Natural language search query.
        top_k: Maximum number of results to return (default 10).
        threshold: Minimum relevance score in [0, 1] (default 0.3).
        worktree: Optional worktree label to filter by.

    Returns:
        Dict with 'results' list and 'count'. Each result contains session_id,
        title, text, score, and created_at.
    """
    return _search_transcripts(query, top_k=top_k, threshold=threshold, worktree=worktree)


@mcp.tool
def get_artifact(artifact_id: int) -> dict:
    """Retrieve a single artifact by ID.

    Returns the artifact's section type, full text, transcript ID,
    and creation timestamp.

    Args:
        artifact_id: The artifact's database ID.

    Returns:
        Dict with artifact details, or error if not found.
    """
    return _get_artifact(artifact_id)


@mcp.tool
def get_transcript_detail(transcript_id: int) -> dict:
    """Retrieve a transcript's artifact sections and metadata.

    Returns all artifact sections (summary, knowledge, decisions,
    constraints, actions) for a transcript, plus session timing info.
    Use this to drill down on transcript hits from search results.

    Args:
        transcript_id: The transcript's database ID.

    Returns:
        Dict with transcript details and sections dict, or error if not found.
    """
    return _get_transcript_detail(transcript_id)


def _get_session(session_id: str) -> dict:
    """Core get_session logic, called by the MCP tool wrapper."""
    result = engine.get_session(session_id)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


@mcp.tool
def get_session(session_id: str) -> dict:
    """Retrieve a session's transcript and extraction sections by session ID.

    Look up a worker session by its Claude session ID to check its current
    state and review its extracted sections (summary, knowledge, decisions,
    constraints, actions).

    Args:
        session_id: The Claude session ID (from CLAUDE_SESSION_ID).

    Returns:
        Dict with session_id, started_at, ended_at, and sections dict,
        or error if not found.
    """
    return _get_session(session_id)


def main() -> None:
    """Entry point for the observer-search MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
