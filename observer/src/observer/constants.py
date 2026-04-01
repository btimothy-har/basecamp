"""Observer constants."""

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
REFINING_STALE_THRESHOLD = 600  # 10 minutes — reset REFINING items older than this
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
SEARCH_OVERFETCH_FACTOR = 5
SEARCH_SEMANTIC_WEIGHT = 0.6  # blend weight for semantic similarity
SEARCH_KEYWORD_WEIGHT = 0.4  # blend weight for FTS keyword relevance
# Database paths (SQLite + ChromaDB)
DB_PATH = BASECAMP_DIR / "observer.db"
DB_URL = f"sqlite:///{DB_PATH}"
CHROMA_DIR = BASECAMP_DIR / "chroma"
