"""Well-known filesystem locations ``basecamp doctor`` inspects.

Bundled as an injectable :class:`Locations` so the reference and runtime checks
can be pointed at a temporary root under test. :meth:`Locations.default`
resolves the real ``~`` / ``~/.pi/basecamp`` tree. The scaffold-dir properties
mirror :mod:`basecamp.core.paths` (they are the same paths when ``basecamp_dir``
is the default); the runtime paths mirror the hub daemon layout
(``~/.pi/basecamp/swarm/``) and the retired Puppeteer browser profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from basecamp.core.paths import BASECAMP_CONFIG_DIR


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
        return self.basecamp_dir / "context"

    @property
    def styles_dir(self) -> Path:
        """User-supplied working-style overrides directory."""
        return self.basecamp_dir / "styles"

    @property
    def prompts_dir(self) -> Path:
        """User-supplied prompt-fragment overrides directory."""
        return self.basecamp_dir / "prompts"

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
        return self.basecamp_dir / "swarm" / "daemon.pid"
