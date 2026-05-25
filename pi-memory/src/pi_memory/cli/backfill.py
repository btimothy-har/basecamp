"""Raw local transcript backfill."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pi_memory.constants import DEFAULT_TRANSCRIPT_ROOTS
from pi_memory.db.database import Database
from pi_memory.ingest import IngestResult, ObserveInput, TranscriptIngestService
from pi_memory.transcripts import PiTranscriptParser, discover_transcript_paths

BackfillStatus = Literal["imported", "would_import", "skipped", "error"]
MISSING_SESSION_ID_REASON = "missing_session_id"


@dataclass(frozen=True)
class BackfillFileResult:
    """Result for one transcript considered by backfill."""

    path: Path
    status: BackfillStatus
    session_id: str | None = None
    reason: str | None = None
    ingest_result: IngestResult | None = None

    @property
    def entries_ingested(self) -> int:
        if self.ingest_result is None:
            return 0
        return self.ingest_result.entries_ingested


@dataclass(frozen=True)
class BackfillResult:
    """Summary of a raw transcript backfill run."""

    db_url: str
    roots: tuple[Path, ...]
    dry_run: bool
    files: tuple[BackfillFileResult, ...]

    @property
    def discovered(self) -> int:
        return len(self.files)

    @property
    def imported(self) -> int:
        return self._count("imported")

    @property
    def would_import(self) -> int:
        return self._count("would_import")

    @property
    def skipped(self) -> int:
        return self._count("skipped")

    @property
    def errors(self) -> int:
        return self._count("error")

    @property
    def entries_ingested(self) -> int:
        return sum(file.entries_ingested for file in self.files)

    def _count(self, status: BackfillStatus) -> int:
        return sum(1 for file in self.files if file.status == status)


def run_raw_backfill(
    *,
    db_url: str,
    roots: Iterable[Path | str] | None = None,
    dry_run: bool = False,
) -> BackfillResult:
    """Backfill raw transcript entries from local Pi JSONL files."""
    effective_roots = _effective_roots(roots)
    parser = PiTranscriptParser()
    transcript_paths = discover_transcript_paths(effective_roots)
    if dry_run:
        files = tuple(_dry_run_result(path, parser) for path in transcript_paths)
        return BackfillResult(db_url=db_url, roots=effective_roots, dry_run=True, files=files)

    database = Database(db_url)
    ingest_service = TranscriptIngestService(database=database, parser=parser)
    try:
        files = tuple(_backfill_file(path, parser, ingest_service) for path in transcript_paths)
    finally:
        database.close_if_open()

    return BackfillResult(db_url=db_url, roots=effective_roots, dry_run=False, files=files)


def _effective_roots(roots: Iterable[Path | str] | None) -> tuple[Path, ...]:
    return tuple(Path(root).expanduser() for root in (DEFAULT_TRANSCRIPT_ROOTS if roots is None else roots))


def _dry_run_result(path: Path, parser: PiTranscriptParser) -> BackfillFileResult:
    try:
        session_id = parser.session_id(path)
    except OSError as error:
        return BackfillFileResult(path=path, status="error", reason=str(error))

    if session_id is None:
        return BackfillFileResult(path=path, status="skipped", reason=MISSING_SESSION_ID_REASON)
    return BackfillFileResult(path=path, status="would_import", session_id=session_id)


def _backfill_file(
    path: Path,
    parser: PiTranscriptParser,
    ingest_service: TranscriptIngestService,
) -> BackfillFileResult:
    try:
        session_id = parser.session_id(path)
    except OSError as error:
        return BackfillFileResult(path=path, status="error", reason=str(error))

    if session_id is None:
        return BackfillFileResult(path=path, status="skipped", reason=MISSING_SESSION_ID_REASON)

    try:
        ingest_result = ingest_service.observe(ObserveInput(session_id=session_id, transcript_path=path))
    except OSError as error:
        return BackfillFileResult(path=path, status="error", session_id=session_id, reason=str(error))

    return BackfillFileResult(path=path, status="imported", session_id=session_id, ingest_result=ingest_result)
