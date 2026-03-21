"""Multiprocessing worker targets for ingestion, refining, extraction, and indexing.

These are top-level functions (not methods) because ``multiprocessing.Process``
needs picklable targets. Each worker acquires an advisory file lock, does its
work, then releases the lock and exits.
"""

import fcntl
import functools
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from observer.data.transcript import Transcript
from observer.pipeline.extraction import TranscriptExtractor
from observer.pipeline.indexing import SearchIndexer
from observer.pipeline.parser import TranscriptParser
from observer.pipeline.refining import EventRefiner
from observer.services.db import Database
from observer.services.logger import configure_logging_worker

logger = logging.getLogger(__name__)


def worker_process(func: Callable[..., None]) -> Callable[..., None]:
    """Decorator for multiprocessing worker targets.

    Handles two process-safety concerns:
    1. Logging — pops ``log_queue`` from kwargs and configures a QueueHandler
       so all worker log output flows through the daemon's QueueListener.
    2. Database — disposes any inherited Database singleton (not fork-safe)
       before the worker runs, and closes it on exit.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> None:
        log_queue = kwargs.pop("log_queue", None)
        if log_queue is not None:
            configure_logging_worker(log_queue)
        Database.close_if_open()
        try:
            func(*args, **kwargs)
        finally:
            Database.close_if_open()

    return wrapper


@worker_process
def ingest_worker(
    transcript_id: int,
    file_mtime: int,
    lock_dir: Path,
) -> None:
    """Worker process target. Locks, ingests, updates mtime, unlocks."""
    lock_path = lock_dir / f"transcript_{transcript_id}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        logger.info("Lock held for transcript %d, skipping", transcript_id)
        return

    try:
        transcript = Transcript.get(transcript_id)
        if transcript is None:
            logger.warning("Transcript %d not found, skipping", transcript_id)
            # Write skip marker so daemon stops retrying this ID
            (lock_dir / f"notfound_{transcript_id}").touch()
            return

        transcript.last_mtime = file_mtime
        TranscriptParser().ingest(transcript)
    except Exception:
        logger.exception("Worker failed for transcript %d", transcript_id)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@worker_process
def refine_worker(lock_dir: Path) -> None:
    """Worker process target for event refining. Acquires advisory lock, runs batch."""
    lock_path = lock_dir / "refining.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        logger.info("Refining lock held, skipping")
        return

    try:
        EventRefiner.refine_batch(Database())
    except Exception:
        logger.exception("Refining worker failed")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@worker_process
def extraction_worker(transcript_id: int, lock_dir: Path) -> None:
    """Worker process target for transcript-level extraction.

    Fires when a transcript has been inactive (no new file writes) for
    INACTIVITY_TIMEOUT seconds. Uses a per-transcript lock so multiple
    transcripts can be extracted concurrently.
    """
    lock_path = lock_dir / f"extraction_{transcript_id}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        logger.info("Extraction lock held for transcript %d, skipping", transcript_id)
        return

    try:
        TranscriptExtractor.extract_transcript(Database(), transcript_id)
    except Exception:
        logger.exception("Extraction worker failed for transcript %d", transcript_id)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


@worker_process
def index_worker(lock_dir: Path) -> None:
    """Worker process target for search indexing. Acquires advisory lock, runs batch."""
    lock_path = lock_dir / "indexing.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        logger.info("Indexing lock held, skipping")
        return

    try:
        SearchIndexer.index_batch(Database())
    except Exception:
        logger.exception("Indexing worker failed")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
