"""Daemon polling loop with multiprocessing workers.

The daemon is a read-only detector: queries active transcripts, stats files,
and spawns isolated worker processes to ingest. Workers are ephemeral — lock,
ingest, update state, unlock, exit.
"""

from observer.daemon.daemon import Daemon
from observer.daemon.workers import extraction_worker, index_worker, ingest_worker, refine_worker

__all__ = ["Daemon", "extraction_worker", "index_worker", "ingest_worker", "refine_worker"]
