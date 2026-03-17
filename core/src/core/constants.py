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
USER_ASSEMBLED_PROMPTS_DIR = USER_PROMPTS_DIR / "assembled"
SCRATCH_BASE = Path("/tmp/claude-workspace")
TASKS_DIR = SCRATCH_BASE / "tasks"
OBSERVER_CONFIG = USER_DIR / "observer" / "config.json"

# String constants
CLAUDE_COMMAND = "claude"
