"""Observer constants."""

import os
from pathlib import Path

# Read paths — where Claude stores transcripts
CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# State paths — where observer stores its own data
BASECAMP_DIR = Path.home() / ".basecamp"
OBSERVER_DIR = BASECAMP_DIR / "observer"
LOG_FILE = OBSERVER_DIR / "observer.log"

DEFAULT_STALE_THRESHOLD = 300

# Notebook (viz) settings
NOTEBOOK_LOG_FILE = OBSERVER_DIR / "notebook.log"
VIZ_PORT = 15028
VIZ_HOST = "localhost"
VIZ_MAX_FAILURES = 3
VIZ_FAILURE_WINDOW = 60  # seconds

TRANSCRIPT_EXTENSION = ".jsonl"

# Extraction settings
REFINING_MAX_WORKERS = 15
EXTRACTION_TIMEOUT = 120
DEFAULT_OBSERVER_MODEL = "sonnet"

EXTRACTABLE_EVENT_TYPES = frozenset({"user", "assistant"})

# Embedding settings
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384
MODEL_CACHE_DIR = OBSERVER_DIR / "models"

# Search settings
SEARCH_DEFAULT_TOP_K = 10
SEARCH_DEFAULT_THRESHOLD = 0.3
SEARCH_TIME_DECAY_SCALE_DAYS = 30.0  # age at which recency bonus = 0.5
SEARCH_TIME_DECAY_POWER = 0.5  # power-law exponent; lower = slower decay
SEARCH_DEDUP_SIMILARITY = 0.9
SEARCH_OVERFETCH_FACTOR = 5

# Container (local dev database)
DB_CONTAINER_NAME = "observer-pg"
DB_IMAGE = "docker.io/pgvector/pgvector:pg17"
DB_VOLUME_NAME = "observer_data"
DB_PORT = 15432
DB_USER = os.environ.get("OBSERVER_DB_USER", "observer")
DB_PASSWORD = os.environ.get("OBSERVER_DB_PASSWORD", "observer")
DB_NAME = os.environ.get("OBSERVER_DB_NAME", "observer")
DB_PG_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost:{DB_PORT}/{DB_NAME}"
