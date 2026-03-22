# ruff: noqa: PLC0415
"""Semantic memory retrieval CLI for Claude Code sessions.

Thin wrapper over the observer search engine. Reads BASECAMP_REPO and
CLAUDE_SESSION_ID from the environment to scope searches automatically.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click

VALID_ARTIFACT_TYPES = frozenset({"knowledge", "decisions", "constraints", "actions"})


def _emit(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    click.echo(json.dumps(data))


def _error(message: str) -> None:
    """Write a JSON error to stdout and exit with code 1."""
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
    from observer.exceptions import ObserverError
    from observer.mcp import engine

    project_name = None if cross_project else os.environ.get("BASECAMP_REPO")
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
            # Artifact search — post-filter to requested types
            raw = engine.search_artifacts(
                query,
                project_name,
                top_k=top_k,
                threshold=threshold,
                session_id=session_id,
            )
            requested = set(parsed_types)
            results = [r for r in raw if r.get("type") in requested]
    except ObserverError as e:
        _error(str(e))
    except Exception as e:
        _error(f"Search failed: {e}")

    _emit({"results": results, "count": len(results)})


@click.group(invoke_without_command=True)
@click.argument("query", required=False)
@click.option("--type", "-t", "types", default=None, help="Comma-separated artifact types to search: knowledge, decisions, constraints, actions")
@click.option("--cross-project", "-x", is_flag=True, help="Search across all projects (default: scoped to BASECAMP_REPO)")
@click.option("--top-k", "-k", default=10, show_default=True, help="Max results to return")
@click.option("--threshold", default=0.3, show_default=True, help="Minimum relevance score")
@click.pass_context
def main(
    ctx: click.Context,
    query: str | None,
    types: str | None,
    cross_project: bool,
    top_k: int,
    threshold: float,
) -> None:
    """Semantic memory retrieval for Claude Code sessions.

    Search past sessions by topic (default), or drill into specific artifact
    types with --type. Use `recall session <id>` to fetch full session detail.
    """
    if ctx.invoked_subcommand is not None:
        return

    if not query:
        _error("Query required")

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
    from observer.exceptions import ObserverError
    from observer.mcp import engine

    try:
        result = engine.get_session(session_id)
    except ObserverError as e:
        _error(str(e))
    except Exception as e:
        _error(f"Session lookup failed: {e}")

    if result is None:
        _error(f"Session not found: {session_id}")

    _emit(result)
