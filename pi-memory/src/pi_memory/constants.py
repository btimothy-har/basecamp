"""Constants for the Pi memory service."""

from pathlib import Path
from typing import Final

SERVICE_NAME: Final = "pi-memory"
SERVICE_VERSION: Final = "0.1.0"

DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765

MEMORY_DIR: Final = Path("~/.pi/memory").expanduser()
MEMORY_DB_PATH: Final = MEMORY_DIR / "memory.db"
MEMORY_DB_URL: Final = f"sqlite:///{MEMORY_DB_PATH}"
MEMORY_CHROMA_DIR: Final = MEMORY_DIR / "chroma"
MEMORY_MODEL_CACHE_DIR: Final = MEMORY_DIR / "models"
SERVER_METADATA_PATH: Final = MEMORY_DIR / "server.json"
SERVER_LOCK_PATH: Final = MEMORY_DIR / "server.lock"
LOGS_DIR: Final = MEMORY_DIR / "logs"
