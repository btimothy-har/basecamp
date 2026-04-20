"""Logging configuration for observer."""

import logging
import sys
from logging.handlers import RotatingFileHandler

from basecamp import constants

# 10 MB per file, keep 3 backups (40 MB max on disk)
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 3


def _make_formatter() -> logging.Formatter:
    return logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


def _suppress_noisy_loggers() -> None:
    for name in ("httpx", "huggingface_hub", "sentence_transformers"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(*, foreground: bool = False) -> None:
    """Set up root logger with a direct handler.

    Used by the process CLI command for background LLM work.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()

    if foreground:
        handler: logging.Handler = logging.StreamHandler(sys.stderr)
    else:
        log_file = constants.OBSERVER_LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT)

    handler.setFormatter(_make_formatter())
    root.addHandler(handler)
    _suppress_noisy_loggers()
