"""Utilities for basecamp-core."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(
    path: Path,
    data: dict | list,
    *,
    mode: int = 0o644,
    dir_mode: int = 0o755,
) -> None:
    """Write JSON to path atomically.

    Creates the parent directory if absent, writes to a unique sibling temp
    file (via mkstemp), fsyncs it, sets exact permissions via fchmod (unaffected
    by umask), renames into place, then fsyncs the parent directory. Readers
    see either the old or the new complete file — never a partial write. The
    temp file is removed on any exception.

    Args:
        path: Destination file path.
        data: JSON-serializable data.
        mode: File permission bits (default 0o644). Use 0o600 for sensitive files.
        dir_mode: Parent directory permission bits when created (default 0o755).
    """
    path.parent.mkdir(parents=True, mode=dir_mode, exist_ok=True)
    content = (json.dumps(data, indent=2) + os.linesep).encode()
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        try:
            os.write(fd, content)
            os.fsync(fd)
            os.fchmod(fd, mode)
        finally:
            os.close(fd)
        os.replace(tmp_name, path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    # Fsync the parent directory to make the rename durable across crashes.
    dir_fd = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
