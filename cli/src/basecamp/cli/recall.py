# ruff: noqa: PLC0415
"""Semantic memory retrieval CLI for Claude Code sessions.

Thin wrapper over the observer search search. Reads BASECAMP_REPO and
CLAUDE_SESSION_ID from the environment to scope searches automatically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
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


def _parse_date(ctx: click.Context, param: click.Parameter, value: str | None) -> datetime | None:  # noqa: ARG001
    """Click callback that parses ISO date strings into UTC datetimes.

    Accepts ``YYYY-MM-DD`` (midnight UTC) or full ISO datetime.
    """
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(value) if "T" in value else datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007
    except ValueError:
        msg = f"Invalid date: {value!r}. Use YYYY-MM-DD or ISO datetime."
        raise click.BadParameter(msg) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _resolve_project(cross_project: bool) -> str | None:  # noqa: FBT001
    """Return the project name from BASECAMP_REPO, or None for cross-project."""
    if cross_project:
        return None
    project_name = os.environ.get("BASECAMP_REPO")
    if not project_name:
        _error(
            "BASECAMP_REPO is not set — cannot scope to current project. Use --cross-project to search all projects."
        )
    return project_name


def _parse_types(types: str | None) -> list[str] | None:
    """Validate and split a comma-separated type string."""
    if types is None:
        return None
    parsed = [t.strip() for t in types.split(",") if t.strip()]
    invalid = [t for t in parsed if t not in VALID_ARTIFACT_TYPES]
    if invalid:
        _error(f"Invalid type(s): {', '.join(invalid)}. Valid: {', '.join(sorted(VALID_ARTIFACT_TYPES))}")
    return parsed


def _run_search(
    query: str,
    *,
    types: str | None,
    cross_project: bool,
    top_k: int,
    threshold: float,
    after: datetime | None = None,
    before: datetime | None = None,
) -> None:
    """Execute search and emit JSON results."""
    from observer import search

    project_name = _resolve_project(cross_project)
    session_id = os.environ.get("CLAUDE_SESSION_ID")
    parsed_types = _parse_types(types)

    try:
        if parsed_types is None:
            raw = search.search_transcripts(
                query,
                project_name,
                top_k=top_k,
                threshold=threshold,
                session_id=session_id,
                after=after,
                before=before,
            )
            results = [{**r, "type": "summary"} for r in raw]
        else:
            results = search.search_artifacts(
                query,
                project_name,
                top_k=top_k,
                threshold=threshold,
                session_id=session_id,
                section_types=parsed_types,
                after=after,
                before=before,
            )
    except Exception:
        logger.exception("Search failed")
        _error("Search failed — check observer logs for details")

    _emit({"results": results, "count": len(results)})


def _run_list(
    *,
    types: str | None,
    cross_project: bool,
    top_k: int,
    after: datetime | None = None,
    before: datetime | None = None,
    filter_session_id: str | None = None,
) -> None:
    """Execute parametric list and emit JSON results."""
    from observer import search

    project_name = _resolve_project(cross_project)
    parsed_types = _parse_types(types)

    try:
        if parsed_types is None and filter_session_id is None:
            results = search.list_transcripts(
                project_name,
                after=after,
                before=before,
                top_k=top_k,
            )
        else:
            results = search.list_artifacts(
                project_name,
                after=after,
                before=before,
                session_id=filter_session_id,
                section_types=parsed_types,
                top_k=top_k,
            )
    except Exception:
        logger.exception("List failed")
        _error("List failed — check observer logs for details")

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
@click.option("--after", callback=_parse_date, default=None, help="Only include results after this date (YYYY-MM-DD)")
@click.option("--before", callback=_parse_date, default=None, help="Only include results before this date (YYYY-MM-DD)")
def search(
    query: str,
    types: str | None,
    cross_project: bool,  # noqa: FBT001
    top_k: int,
    threshold: float,
    after: datetime | None,
    before: datetime | None,
) -> None:
    """Search past sessions by topic or artifact type."""
    _run_search(
        query,
        types=types,
        cross_project=cross_project,
        top_k=top_k,
        threshold=threshold,
        after=after,
        before=before,
    )


@main.command("list")
@click.option("--type", "-t", "types", default=None, help="Artifact types: knowledge, decisions, constraints, actions")
@click.option("--cross-project", "-x", is_flag=True, help="List across all projects")
@click.option("--top-k", "-k", default=10, show_default=True, help="Max results to return")
@click.option("--after", callback=_parse_date, default=None, help="Only include results after this date (YYYY-MM-DD)")
@click.option("--before", callback=_parse_date, default=None, help="Only include results before this date (YYYY-MM-DD)")
@click.option("--session", "filter_session_id", default=None, help="Filter artifacts within a specific session")
def list_cmd(
    types: str | None,
    cross_project: bool,  # noqa: FBT001
    top_k: int,
    after: datetime | None,
    before: datetime | None,
    filter_session_id: str | None,
) -> None:
    """Browse sessions and artifacts by date range and filters."""
    _run_list(
        types=types,
        cross_project=cross_project,
        top_k=top_k,
        after=after,
        before=before,
        filter_session_id=filter_session_id,
    )


@main.command()
@click.argument("session_id")
def session(session_id: str) -> None:
    """Retrieve full session detail by session ID."""
    from observer import search

    try:
        result = search.get_session(session_id)
    except Exception:
        logger.exception("Session lookup failed")
        _error("Session lookup failed — check observer logs for details")

    if result is None:
        _error(f"Session not found: {session_id}")

    _emit(result)
