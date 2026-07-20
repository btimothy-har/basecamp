"""Runtime checks: reclaim regenerable runtime state only once it is unused.

The v1 target is the retired Puppeteer browser profile
(``~/.pi/basecamp/browser/profile``). It is *superseded by definition* — the
current browser uses a Playwright-owned profile elsewhere — so the staleness
test reduces to two guards: no live process holds it (its Chrome ``SingletonLock``
names no living pid) and it has gone cold (nothing modified within
``stale_days``). A warm or held profile is kept and not even offered. Reclaim is
destructive (a profile can hold saved logins), so the finding is a ``CLEAN``
remedy the run layer only applies after explicit confirmation.
"""

from __future__ import annotations

import contextlib
import os
import time
from dataclasses import dataclass
from pathlib import Path

from basecamp.core.doctor import clean
from basecamp.core.doctor.finding import Finding, Remedy, Severity
from basecamp.core.doctor.liveness import pid_alive
from basecamp.core.doctor.locations import Locations

GROUP = "Runtime"

_SECONDS_PER_DAY = 86400
_WALK_FILE_CAP = 5000


@dataclass(frozen=True)
class ProfileStatus:
    """Whether a browser profile is currently held and how long it has been idle."""

    in_use: bool
    age_days: int


def check_runtime(locations: Locations, stale_days: int) -> list[Finding]:
    """Offer to reclaim runtime state that is provably unused."""
    return _check_browser_profile(locations.browser_profile, stale_days)


def _check_browser_profile(profile: Path, stale_days: int) -> list[Finding]:
    if not profile.is_dir():
        return []
    status = classify_profile(profile)
    if status.in_use or status.age_days < stale_days:
        return []  # held or still warm — keep it
    detail = (
        f"{profile} — last modified {status.age_days}d ago; retired Puppeteer profile, "
        "superseded by Playwright's managed profile. May hold saved logins/cookies."
    )
    return [
        Finding(
            GROUP,
            Severity.WARNING,
            "retired browser profile is unused and can be reclaimed.",
            remedy=Remedy.CLEAN,
            detail=detail,
            action=f"reclaim {profile}",
            apply=lambda: clean.reclaim_dir(profile),
        )
    ]


def classify_profile(profile: Path) -> ProfileStatus:
    """Classify a browser profile as in-use/idle by its lock and modification time."""
    return ProfileStatus(in_use=_has_live_holder(profile), age_days=_age_days(profile))


def _has_live_holder(profile: Path) -> bool:
    """True when a Chrome ``SingletonLock`` in the profile names a living process."""
    try:
        target = os.readlink(profile / "SingletonLock")
    except OSError:
        return False
    _, _, pid_text = target.rpartition("-")
    try:
        pid = int(pid_text)
    except ValueError:
        return False
    return pid_alive(pid)


def _age_days(profile: Path) -> int:
    """Whole days since the newest modification anywhere in the profile tree."""
    newest = _newest_mtime(profile)
    return int((time.time() - newest) // _SECONDS_PER_DAY)


def _newest_mtime(root: Path) -> float:
    """Newest mtime across the tree, bounded to a file cap so a huge profile stays cheap."""
    newest = 0.0
    scanned = 0
    for path in root.rglob("*"):
        with contextlib.suppress(OSError):
            newest = max(newest, path.stat().st_mtime)
        scanned += 1
        if scanned >= _WALK_FILE_CAP:
            break
    with contextlib.suppress(OSError):
        newest = max(newest, root.stat().st_mtime)
    return newest
