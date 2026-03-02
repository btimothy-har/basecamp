"""Path and string constants for the basecamp launcher."""

import os
import tempfile
from pathlib import Path

from core.settings import settings

# Workspace root — written to config.json by install.py during installation.
# In test environments (TESTING=1), fall back to a placeholder so the module
# can be imported without a real installation.
_workspace_dir = settings.workspace_dir
if not _workspace_dir:
    if os.environ.get("TESTING"):
        _workspace_dir = str(Path(tempfile.gettempdir()) / "basecamp-test")
    else:
        msg = "basecamp not installed. Run: uv run install.py"
        raise RuntimeError(msg)

SCRIPT_DIR = Path(_workspace_dir)
WORKSPACE_PLUGIN_DIR = SCRIPT_DIR / "plugins" / "workspace"

# User directory — all user-specific files live here, outside the repo
USER_DIR = Path.home() / ".basecamp"
USER_PROMPTS_DIR = USER_DIR / "prompts"
USER_WORKING_STYLES_DIR = USER_PROMPTS_DIR / "working_styles"
USER_CONTEXT_DIR = USER_PROMPTS_DIR / "context"
SCRATCH_BASE = Path("/tmp/claude-workspace")
OBSERVER_CONFIG = USER_DIR / "observer" / "config.json"

# String constants
CLAUDE_COMMAND = "claude"
