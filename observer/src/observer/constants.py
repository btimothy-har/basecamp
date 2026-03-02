"""Observer daemon constants."""

import os
from pathlib import Path

# Read paths — where Claude stores transcripts
CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"

# State paths — where observer stores its own data
BASECAMP_DIR = Path.home() / ".basecamp"
OBSERVER_DIR = BASECAMP_DIR / "observer"
PID_FILE = OBSERVER_DIR / "observer.pid"
LOG_FILE = OBSERVER_DIR / "observer.log"

TICK_INTERVAL = 1  # seconds between scheduler ticks
PROCESS_INTERVAL = 6  # seconds between processing spawns
INDEX_INTERVAL = 15  # seconds between indexing spawns
MAX_INGEST_WORKERS = 8  # max ingest processes spawned per poll cycle
DEFAULT_STALE_THRESHOLD = 300

# Notebook (viz) settings
NOTEBOOK_LOG_FILE = OBSERVER_DIR / "notebook.log"
VIZ_PORT = 15028
VIZ_HOST = "localhost"
VIZ_MAX_FAILURES = 3
VIZ_FAILURE_WINDOW = 60  # seconds

TRANSCRIPT_EXTENSION = ".jsonl"

# Extraction settings
REFINING_BATCH_LIMIT = 200
REFINE_INTERVAL = 4  # seconds between refining spawns
EXTRACTION_BATCH_LIMIT = 200
EXTRACTION_TIMEOUT = 120
DEFAULT_EXTRACTION_MODEL = "sonnet"
DEFAULT_SUMMARY_MODEL = "haiku"

EXTRACTABLE_EVENT_TYPES = frozenset({"user", "assistant"})

# Embedding settings
EMBEDDING_BATCH_LIMIT = 500
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
SEARCH_SIBLING_THRESHOLD = 0.5  # min similarity to result artifact for session context

# MCP server
MCP_SERVER_NAME = "observer"
MCP_SERVER_INSTRUCTIONS = """\
Semantic memory over past Claude Code sessions.

Results are scoped to the current project and exclude the active session.

Two retrieval pathways:

1. search_artifacts — find specific facts, decisions, and constraints.
   Results include session_context (sibling artifacts from the same
   session). Drill down with get_artifact for full details including
   the original prompt (prompted_by) that triggered the work.

2. search_transcripts — find relevant past sessions by summary.
   Drill down with get_transcript_summary for the full structured
   summary.

Start with search_artifacts for specific questions. Use
search_transcripts when you need broader context about what was
done in past sessions."""

# Container (local dev database)
DB_CONTAINER_NAME = "observer-pg"
DB_IMAGE = "docker.io/pgvector/pgvector:pg17"
DB_VOLUME_NAME = "observer_data"
DB_PORT = 15432
DB_USER = os.environ.get("OBSERVER_DB_USER", "observer")
DB_PASSWORD = os.environ.get("OBSERVER_DB_PASSWORD", "observer")
DB_NAME = os.environ.get("OBSERVER_DB_NAME", "observer")
DB_PG_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@localhost:{DB_PORT}/{DB_NAME}"
