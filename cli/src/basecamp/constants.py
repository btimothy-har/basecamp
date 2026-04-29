"""Path and string constants for the basecamp launcher."""

import os
import tempfile
from pathlib import Path

from basecamp.settings import settings

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

# User directories
PI_DIR = Path.home() / ".pi"
USER_DIR = PI_DIR / "basecamp"
USER_PROMPTS_DIR = PI_DIR / "prompts"
USER_STYLES_DIR = PI_DIR / "styles"
USER_LANGUAGES_DIR = PI_DIR / "languages"
USER_CONTEXT_DIR = PI_DIR / "context"
USER_AGENTS_DIR = PI_DIR / "agents"

# Observer state paths
OBSERVER_DIR = PI_DIR / "observer"
OBSERVER_LOG_FILE = OBSERVER_DIR / "observer.log"
OBSERVER_DB_PATH = OBSERVER_DIR / "observer.db"
OBSERVER_DB_URL = f"sqlite:///{OBSERVER_DB_PATH}"
OBSERVER_CHROMA_DIR = OBSERVER_DIR / "chroma"
OBSERVER_MODEL_CACHE_DIR = OBSERVER_DIR / "models"
