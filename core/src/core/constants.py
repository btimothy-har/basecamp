"""Path and string constants for the basecamp launcher."""

import os
import tempfile
from pathlib import Path

from core.settings import settings

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

# User directory — all user-specific files live here, outside the repo
USER_DIR = Path.home() / ".basecamp"
USER_PROMPTS_DIR = USER_DIR / "prompts"
USER_WORKING_STYLES_DIR = USER_PROMPTS_DIR / "working_styles"
USER_CONTEXT_DIR = USER_PROMPTS_DIR / "context"
CACHE_DIR = USER_DIR / ".cached"
SCRATCH_BASE = Path("/tmp/claude-workspace")
WORKERS_BASE = SCRATCH_BASE / "workers"
INBOX_BASE = SCRATCH_BASE / "inbox"
WORKERS_INDEX_DIR = USER_DIR / "workers"
OBSERVER_CONFIG = USER_DIR / "observer" / "config.json"

# CLI paths
PI_COMMAND = "pi"
EXTENSION_DIR = SCRIPT_DIR / "extension"

# Claude CLI paths (still used by worker ops and handoff — remove when migrated)
CLAUDE_COMMAND = "claude"
CLAUDE_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
