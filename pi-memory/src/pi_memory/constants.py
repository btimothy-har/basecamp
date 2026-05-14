"""Constants for the Pi memory service."""

from pathlib import Path
from typing import Final

SERVICE_NAME: Final = "pi-memory"
SERVICE_VERSION: Final = "0.1.0"

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765

MEMORY_DIR: Final = Path("~/.pi/memory").expanduser()
SERVER_METADATA_PATH: Final = MEMORY_DIR / "server.json"
SERVER_LOCK_PATH: Final = MEMORY_DIR / "server.lock"
LOGS_DIR: Final = MEMORY_DIR / "logs"
