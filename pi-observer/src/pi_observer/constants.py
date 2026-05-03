"""Observer paths, tuning parameters, thresholds, and weights."""

from pathlib import Path

# User state paths
PI_DIR = Path.home() / ".pi"
OBSERVER_DIR = PI_DIR / "observer"
OBSERVER_CONFIG_PATH = OBSERVER_DIR / "config.json"
OBSERVER_LOG_FILE = OBSERVER_DIR / "observer.log"
OBSERVER_DB_PATH = OBSERVER_DIR / "observer.db"
OBSERVER_DB_URL = f"sqlite:///{OBSERVER_DB_PATH}"
OBSERVER_CHROMA_DIR = OBSERVER_DIR / "chroma"
OBSERVER_MODEL_CACHE_DIR = OBSERVER_DIR / "models"

# Pipeline thresholds
DEFAULT_STALE_THRESHOLD = 300
REFINING_MAX_WORKERS = 15
REFINING_STALE_THRESHOLD = 600  # 10 minutes — reset REFINING items older than this

# Event classification
EXTRACTABLE_EVENT_TYPES = frozenset({"user", "assistant", "toolResult"})

# Embedding settings
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

# Search settings
SEARCH_DEFAULT_TOP_K = 10
SEARCH_DEFAULT_THRESHOLD = 0.3
SEARCH_TIME_DECAY_SCALE_DAYS = 30.0  # age at which recency bonus = 0.5
SEARCH_TIME_DECAY_POWER = 0.5  # power-law exponent; lower = slower decay
SEARCH_OVERFETCH_FACTOR = 5
SEARCH_SEMANTIC_WEIGHT = 0.6  # blend weight for semantic similarity
SEARCH_KEYWORD_WEIGHT = 0.4  # blend weight for FTS keyword relevance
