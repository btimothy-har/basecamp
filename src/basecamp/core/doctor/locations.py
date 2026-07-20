"""Well-known filesystem locations ``basecamp doctor`` inspects.

Bundled as an injectable :class:`Locations` so the reference and runtime checks
can be pointed at a temporary root under test. :meth:`Locations.default`
resolves the real ``~`` / ``~/.pi/basecamp`` tree. The live-tree properties
(scaffold dirs, the daemon pid file) ``rebase`` the canonical
:mod:`basecamp.core.paths` constants onto ``basecamp_dir`` — one source of
truth, resolved under whatever root the doctor was pointed at. Only the two
doctor-specific *retired* locations (the legacy override root and the retired
Puppeteer browser profile) are spelled here, since they are not part of the
live layout ``core.paths`` advertises.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basecamp.core.paths import (
    BASECAMP_CONFIG_DIR,
    DAEMON_PID,
    USER_CONTEXT_DIR,
    USER_PROMPTS_DIR,
    USER_STYLES_DIR,
    rebase,
)


@dataclass(frozen=True)
class Locations:
    """Filesystem roots the doctor's reference and runtime checks resolve against."""

    home: Path
    basecamp_dir: Path

    @classmethod
    def default(cls) -> Locations:
        """Resolve the real user home and basecamp root."""
        return cls(home=Path.home(), basecamp_dir=BASECAMP_CONFIG_DIR)

    @property
    def context_dir(self) -> Path:
        """User-supplied context overrides directory."""
        return rebase(USER_CONTEXT_DIR, self.basecamp_dir)

    @property
    def styles_dir(self) -> Path:
        """User-supplied working-style overrides directory."""
        return rebase(USER_STYLES_DIR, self.basecamp_dir)

    @property
    def prompts_dir(self) -> Path:
        """User-supplied prompt-fragment overrides directory."""
        return rebase(USER_PROMPTS_DIR, self.basecamp_dir)

    @property
    def scaffold_dirs(self) -> tuple[Path, Path, Path]:
        """The three override directories ``basecamp setup`` scaffolds."""
        return (self.context_dir, self.styles_dir, self.prompts_dir)

    @property
    def legacy_overrides_dir(self) -> Path:
        """Pre-rearchitecture override root, abandoned with no auto-migration."""
        return self.basecamp_dir / "workspace"

    @property
    def browser_profile(self) -> Path:
        """The retired Puppeteer browser profile (superseded by Playwright's own)."""
        return self.basecamp_dir / "browser" / "profile"

    @property
    def daemon_pidfile(self) -> Path:
        """The hub daemon's pid file under the swarm runtime dir."""
        return rebase(DAEMON_PID, self.basecamp_dir)
