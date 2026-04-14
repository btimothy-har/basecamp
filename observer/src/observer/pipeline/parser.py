"""Transcript JSONL parser.

Reads transcript files (JSONL) from a byte offset, produces ParsedEvent
records, and persists them as RawEvents. Auto-detects Claude Code vs pi
formats per-line.
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from observer.data.raw_event import RawEvent
from observer.exceptions import TranscriptFileNotFoundError, TranscriptNotSavedError
from observer.services.db import Database


@dataclass(frozen=True, slots=True)
class ParsedEvent:
    """A single parsed transcript event, ready to become a RawEvent."""

    event_type: str
    timestamp: datetime
    content: str
    message_uuid: str | None
    source: str = "pi"


logger = logging.getLogger(__name__)

# Pi-specific non-message entry types to skip
_PI_SKIP_TYPES = frozenset(
    {
        "session",
        "model_change",
        "thinking_level_change",
        "session_info",
        "label",
        "custom",
        "custom_message",
        "compaction",
        "branch_summary",
    }
)

# Claude-specific entry types to skip
_CLAUDE_SKIP_TYPES = frozenset({"file-history-snapshot"})


class TranscriptParser:
    """Parses JSONL transcript files into structured events.

    Reads from a byte offset to support incremental parsing. Incomplete
    trailing lines (writer mid-write) are left unconsumed — the returned
     the offset points to the start of that partial line so the next call
    picks it up.
    """

    def ingest(self, transcript) -> int:
        """Parse new events from the transcript file and persist them.

        Reads from cursor_offset, parses all events into memory, then
        saves each event in its own transaction to minimize DB lock hold
        time. Updates cursor offset in a final transaction.

        Returns the number of events ingested.
        """
        if transcript.id is None:
            raise TranscriptNotSavedError()

        file_path = Path(transcript.path)
        if not file_path.exists():
            raise TranscriptFileNotFoundError(file_path)

        events, new_offset = self.parse(file_path, transcript.cursor_offset)

        for parsed in events:
            raw_event = RawEvent(
                transcript_id=transcript.id,
                event_type=parsed.event_type,
                timestamp=parsed.timestamp,
                content=parsed.content,
                message_uuid=parsed.message_uuid,
                source=parsed.source,
            )
            with Database().session() as session:
                raw_event.save(session)

        transcript.cursor_offset = new_offset
        with Database().session() as session:
            transcript.save(session)

        return len(events)

    def parse(self, path: Path, offset: int = 0) -> tuple[list[ParsedEvent], int]:
        """Parse transcript file from offset, returning events and new offset."""
        raw = self._read_from_offset(path, offset)
        if not raw:
            return [], offset

        lines, consumed = self._split_complete_lines(raw)
        events = self._parse_lines(lines)
        return events, offset + consumed

    def _read_from_offset(self, path: Path, offset: int) -> bytes:
        with open(path, "rb") as f:
            f.seek(offset)
            return f.read()

    def _split_complete_lines(self, raw: bytes) -> tuple[list[bytes], int]:
        """Split raw bytes into complete lines, ignoring any trailing partial line.

        Returns the lines and the byte count consumed (up to and including the
        last newline).
        """
        last_nl = raw.rfind(b"\n")
        if last_nl == -1:
            return [], 0

        complete = raw[: last_nl + 1]
        lines = [line for line in complete.split(b"\n") if line]
        return lines, len(complete)

    def _parse_lines(self, lines: list[bytes]) -> list[ParsedEvent]:
        events: list[ParsedEvent] = []
        for line in lines:
            event = self._parse_line(line)
            if event is not None:
                events.append(event)
        return events

    def _parse_line(self, line: bytes) -> ParsedEvent | None:
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning("Skipping malformed JSON line: %s", line[:120])
            return None

        entry_type = data.get("type")
        if not entry_type:
            logger.info("Skipping line without type field")
            return None

        # Pi format: type is "message", role is nested in message.role
        if entry_type == "message":
            message = data.get("message", {})
            role = message.get("role")
            if not role:
                return None
            ts_raw = data.get("timestamp")
            if not ts_raw:
                return None
            try:
                timestamp = datetime.fromisoformat(ts_raw)
            except (ValueError, TypeError):
                logger.warning("Skipping pi message with unparseable timestamp: %s", ts_raw)
                return None
            return ParsedEvent(
                event_type=role,
                timestamp=timestamp,
                content=line.decode("utf-8", errors="replace"),
                message_uuid=data.get("id"),
                source="pi",
            )

        # Pi non-message entries: skip
        if entry_type in _PI_SKIP_TYPES:
            return None

        # Claude format: type IS the role
        if entry_type in _CLAUDE_SKIP_TYPES:
            return None

        ts_raw = data.get("timestamp")
        if not ts_raw:
            logger.info("Skipping %s event without timestamp", entry_type)
            return None

        try:
            timestamp = datetime.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            logger.warning(
                "Skipping %s event with unparseable timestamp: %s",
                entry_type,
                ts_raw,
            )
            return None

        return ParsedEvent(
            event_type=entry_type,
            timestamp=timestamp,
            content=line.decode("utf-8", errors="replace"),
            message_uuid=data.get("uuid"),
            source="claude",
        )
