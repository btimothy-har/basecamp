# ruff: noqa: PLC0415
"""Semantic memory retrieval CLI for Claude Code sessions.

Thin wrapper over the observer search engine. Reads BASECAMP_REPO and
CLAUDE_SESSION_ID from the environment to scope searches automatically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any, NoReturn

import click

from observer.data.enums import SectionType

VALID_ARTIFACT_TYPES = frozenset(s.value for s in SectionType if s != SectionType.SUMMARY)

logger = logging.getLogger(__name__)


def _emit(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    click.echo(json.dumps(data))


def _error(message: str) -> NoReturn:
    """Write a JSON error to stdout and exit with code 1.

    Errors go to stdout (not stderr) so Claude can parse them as JSON.
    """
    _emit({"error": message})
    sys.exit(1)


def _run_search(
    query: str,
    *,
    types: str | None,
    cross_project: bool,
    top_k: int,
    threshold: float,
) -> None:
    """Execute search and emit JSON results."""
    from observer.mcp import engine

    if cross_project:
        project_name = None
    else:
        project_name = os.environ.get("BASECAMP_REPO")
        if not project_name:
            _error(
                "BASECAMP_REPO is not set — cannot scope search to current project."
                " Use --cross-project to search all projects."
            )

    session_id = os.environ.get("CLAUDE_SESSION_ID")

    parsed_types: list[str] | None = None
    if types is not None:
        parsed_types = [t.strip() for t in types.split(",") if t.strip()]
        invalid = [t for t in parsed_types if t not in VALID_ARTIFACT_TYPES]
        if invalid:
            _error(f"Invalid type(s): {', '.join(invalid)}. Valid: {', '.join(sorted(VALID_ARTIFACT_TYPES))}")

    try:
        if parsed_types is None:
            # Summary search — orientation mode
            raw = engine.search_transcripts(
                query,
                project_name,
                top_k=top_k,
                threshold=threshold,
                session_id=session_id,
            )
            results = [{**r, "type": "summary"} for r in raw]
        else:
            # Artifact search — type filter pushed into the engine query
            results = engine.search_artifacts(
                query,
                project_name,
                top_k=top_k,
                threshold=threshold,
                session_id=session_id,
                section_types=parsed_types,
            )
    except Exception:
        logger.exception("Search failed")
        _error("Search failed — check observer logs for details")

    _emit({"results": results, "count": len(results)})


@click.group()
def main() -> None:
    """Semantic memory retrieval for Claude Code sessions."""


@main.command()
@click.argument("query")
@click.option("--type", "-t", "types", default=None, help="Artifact types: knowledge, decisions, constraints, actions")
@click.option("--cross-project", "-x", is_flag=True, help="Search across all projects")
@click.option("--top-k", "-k", default=10, show_default=True, help="Max results to return")
@click.option("--threshold", default=0.3, show_default=True, help="Minimum relevance score")
def search(
    query: str,
    types: str | None,
    cross_project: bool,  # noqa: FBT001
    top_k: int,
    threshold: float,
) -> None:
    """Search past sessions by topic or artifact type."""
    _run_search(
        query,
        types=types,
        cross_project=cross_project,
        top_k=top_k,
        threshold=threshold,
    )


@main.command()
@click.argument("session_id")
def session(session_id: str) -> None:
    """Retrieve full session detail by session ID."""
    from observer.mcp import engine

    try:
        result = engine.get_session(session_id)
    except Exception:
        logger.exception("Session lookup failed")
        _error("Session lookup failed — check observer logs for details")

    if result is None:
        _error(f"Session not found: {session_id}")

    _emit(result)
