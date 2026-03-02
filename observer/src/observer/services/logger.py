"""Logging configuration for daemon and worker processes.

The daemon uses QueueHandler/QueueListener so that a single thread
writes to the RotatingFileHandler. Workers push LogRecords onto the
shared multiprocessing.Queue via the @worker_process decorator.
"""

import logging
import sys
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler
from multiprocessing import Queue

from observer import constants

# 10 MB per file, keep 3 backups (40 MB max on disk)
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 3


def _make_formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _suppress_noisy_loggers() -> None:
    for name in ("httpx", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(*, foreground: bool = False) -> None:
    """Set up root logger with a direct handler (no queue).

    Used by non-daemon callers or as a fallback.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    if foreground:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    else:
        log_file = constants.LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)

    handler.setFormatter(_make_formatter())
    root.addHandler(handler)
    _suppress_noisy_loggers()


def configure_logging_daemon(*, foreground: bool = False) -> tuple[Queue, QueueListener]:
    """Set up queue-based logging for the daemon process.

    Creates a multiprocessing.Queue, starts a QueueListener that drains
    into either a RotatingFileHandler (background) or StreamHandler
    (foreground), and attaches a QueueHandler to the root logger.

    Returns (queue, listener) — caller owns the listener lifecycle.
    """
    if foreground:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    else:
        log_file = constants.LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)

    handler.setFormatter(_make_formatter())

    log_queue: Queue = Queue()
    listener = QueueListener(log_queue, handler, respect_handler_level=True)
    listener.start()

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(QueueHandler(log_queue))
    _suppress_noisy_loggers()

    return log_queue, listener


def configure_logging_worker(log_queue: Queue) -> None:
    """Set up queue-based logging for a spawned worker process.

    Called by the @worker_process decorator, not by workers directly.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(QueueHandler(log_queue))
    _suppress_noisy_loggers()
