"""Process-liveness probe shared by the prereq (daemon) and runtime checks."""

from __future__ import annotations

import os


def pid_alive(pid: int) -> bool:
    """Return whether ``pid`` names a live process.

    Uses the ``kill(pid, 0)`` liveness convention: a permission error means the
    process exists but is owned by someone else (still alive); a lookup error
    means it is gone. A non-positive pid is never alive.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
