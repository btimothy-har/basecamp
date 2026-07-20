"""Confirmed reclamation of provably-unused runtime state (``--clean``).

The staleness *classification* lives in :mod:`basecamp.core.doctor.checks.runtime`;
this module only performs the removal, once the run layer has verified the
target is unused and the user has confirmed. Kept separate from
:mod:`basecamp.core.doctor.repair` because this is the one path that can delete
regenerable-but-not-free runtime (a browser profile may hold saved logins).
"""

from __future__ import annotations

import shutil
from pathlib import Path


def reclaim_dir(path: Path) -> None:
    """Remove a runtime directory tree.

    The caller is responsible for having classified ``path`` as unused (no live
    holder, cold) and for obtaining explicit confirmation before calling this.
    """
    shutil.rmtree(path)
