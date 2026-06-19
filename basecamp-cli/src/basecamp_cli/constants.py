"""Path and string constants for the basecamp launcher.

Generic pi/basecamp path locations are sourced from
:mod:`basecamp_core.paths`; this module keeps launcher-specific constants
(:data:`SCRIPT_DIR`, :data:`COMPANION_DIR`) that depend on the configured
install directory.
"""

import os
import tempfile
from pathlib import Path

from basecamp_core.paths import (
    PI_DIR,
    USER_CONTEXT_DIR,
    USER_STYLES_DIR,
)

from basecamp_cli.settings import settings

__all__ = [
    "COMPANION_DIR",
    "PI_DIR",
    "SCRIPT_DIR",
    "USER_CONTEXT_DIR",
    "USER_STYLES_DIR",
]

# Install root — written to config.json by install.py during installation.
# In test environments (TESTING=1), fall back to a placeholder so the module
# can be imported without a real installation.
_install_dir = settings.install_dir
if not _install_dir:
    if os.environ.get("TESTING"):
        _install_dir = str(Path(tempfile.gettempdir()) / "basecamp-test")
    else:
        msg = "basecamp not installed. Run: uv run install.py"
        raise RuntimeError(msg)

SCRIPT_DIR = Path(_install_dir)

# User directories (generic locations re-exported for backwards compatibility).
# PI_DIR, USER_STYLES_DIR, and USER_CONTEXT_DIR are sourced from basecamp_core.

COMPANION_DIR = PI_DIR / "companion"
