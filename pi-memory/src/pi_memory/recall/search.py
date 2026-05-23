"""Raw transcript full-text recall search service."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import text

from pi_memory.db.database import (
    Database,
    database,
)

_MAX_LIMIT = 50
_RESERVED_FTS_TOKENS = frozenset({"AND", "OR", "NOT", "NEAR"})
_TOKEN_PATTERN = re.compile(r"[\w]+", re.UNICODE)


@dataclass(frozen=True)
class RawTranscriptRecallResult:
    """Single raw transcript recall hit backed by canonical transcript rows."""

    rank: int
    score: float
    session_id: str
    transcript_id: int
    transcript_path: str
    transcript_entry_id: int
    pi_entry_id: str | None
    entry_type: str
    message_role: str | None
    timestamp: datetime | None
    byte_start: int
    byte_end: int
    excerpt: str
    match_reason: str
    result_type: Literal["raw_transcript"] = "raw_transcript"


@dataclass(frozen=True)
class RawTranscriptSearchResult:
    """Raw transcript search response."""

    query: str
    terms: tuple[str, ...]
    match_query: str | None
    results: tuple[RawTranscriptRecallResult, ...]


class RecallSearchService:
    """Search indexed raw transcript entries via SQLite FTS."""

    def __init__(self, database: Database = database) -> None:
        self._database = database

    def search(
        self,
        query: str,
        limit: int = 10,
        session_id: str | None = None,
    ) -> RawTranscriptSearchResult:
        """Search raw transcript text and return canonical metadata for hits.

        Args:
            query: User-provided search text. Arbitrary FTS MATCH syntax is not
                accepted; the query is tokenized and quoted before execution.
            limit: Maximum number of results. Clamped to 1..50.
            session_id: Optional stable Pi session id filter.

        Returns:
            Search result containing the safe FTS query and canonical hits.
        """
        terms = _search_terms(query)
        match_query = _match_query(terms)
        if match_query is None:
            return RawTranscriptSearchResult(query=query, terms=terms, match_query=None, results=())

        self._database.initialize()
        bounded_limit = _bounded_limit(limit)
        with self._database.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    SELECT
                        bm25(transcript_entries_fts) AS score,
                        sessions.session_id AS session_id,
                        transcripts.id AS transcript_id,
                        transcripts.path AS transcript_path,
                        transcript_entries.id AS transcript_entry_id,
                        transcript_entries.entry_id AS pi_entry_id,
                        transcript_entries.entry_type AS entry_type,
                        transcript_entries.message_role AS message_role,
                        transcript_entries.timestamp AS timestamp,
                        transcript_entries.byte_start AS byte_start,
                        transcript_entries.byte_end AS byte_end,
                        snippet(transcript_entries_fts, 0, '<mark>', '</mark>', '…', 16) AS excerpt
                    FROM transcript_entries_fts
                    JOIN transcript_entries ON transcript_entries.id = transcript_entries_fts.rowid
                    JOIN transcripts ON transcripts.id = transcript_entries.transcript_id
                    JOIN sessions ON sessions.id = transcripts.session_id
                    WHERE transcript_entries_fts MATCH :match_query
                        AND (:session_id IS NULL OR sessions.session_id = :session_id)
                    ORDER BY score ASC, transcript_entries.byte_start ASC, transcript_entries.id ASC
                    LIMIT :limit
                    """,
                ),
                {
                    "limit": bounded_limit,
                    "match_query": match_query,
                    "session_id": session_id,
                },
            ).mappings()

            results = tuple(_recall_result(row, rank, terms) for rank, row in enumerate(rows, start=1))

        return RawTranscriptSearchResult(query=query, terms=terms, match_query=match_query, results=results)


def _search_terms(query: str) -> tuple[str, ...]:
    terms: list[str] = []
    for match in _TOKEN_PATTERN.finditer(query):
        term = match.group(0)
        if term.upper() in _RESERVED_FTS_TOKENS:
            continue
        terms.append(term)
    return tuple(terms)


def _match_query(terms: tuple[str, ...]) -> str | None:
    if not terms:
        return None
    return " ".join(_quote_fts_token(term) for term in terms)


def _quote_fts_token(term: str) -> str:
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


def _bounded_limit(limit: int) -> int:
    return min(max(limit, 1), _MAX_LIMIT)


def _recall_result(row: Mapping[str, Any], rank: int, terms: tuple[str, ...]) -> RawTranscriptRecallResult:
    return RawTranscriptRecallResult(
        rank=rank,
        score=float(row["score"]),
        session_id=str(row["session_id"]),
        transcript_id=int(row["transcript_id"]),
        transcript_path=str(row["transcript_path"]),
        transcript_entry_id=int(row["transcript_entry_id"]),
        pi_entry_id=row["pi_entry_id"],
        entry_type=str(row["entry_type"]),
        message_role=row["message_role"],
        timestamp=_timestamp(row["timestamp"]),
        byte_start=int(row["byte_start"]),
        byte_end=int(row["byte_end"]),
        excerpt=str(row["excerpt"]),
        match_reason=f"Matched raw transcript text for: {', '.join(terms)}",
    )


def _timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return None
