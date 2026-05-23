"""SQLAlchemy models for pi-memory."""

from importlib import import_module

from pi_memory.db.models.analysis import ActivityUnit as ActivityUnit
from pi_memory.db.models.analysis import AnalysisRun as AnalysisRun
from pi_memory.db.models.analysis import Episode as Episode
from pi_memory.db.models.analysis import EpisodeManifest as EpisodeManifest
from pi_memory.db.models.analysis import SessionSnapshotShell as SessionSnapshotShell
from pi_memory.db.models.durable import DurableMemoryAuditEvent as DurableMemoryAuditEvent
from pi_memory.db.models.durable import DurableMemoryItem as DurableMemoryItem
from pi_memory.db.models.durable import DurableMemoryRelation as DurableMemoryRelation
from pi_memory.db.models.durable import DurableMemorySource as DurableMemorySource
from pi_memory.db.models.ingestion import MemorySession as MemorySession
from pi_memory.db.models.ingestion import Observation as Observation
from pi_memory.db.models.ingestion import Transcript as Transcript
from pi_memory.db.models.ingestion import TranscriptEntry as TranscriptEntry
from pi_memory.db.models.interpretation import EpisodeInterpretationSnapshot as EpisodeInterpretationSnapshot
from pi_memory.db.models.interpretation import SessionInterpretationQualityReport as SessionInterpretationQualityReport
from pi_memory.db.models.interpretation import SessionInterpretationSnapshot as SessionInterpretationSnapshot
from pi_memory.db.models.jobs import Job as Job
from pi_memory.db.models.projection import MemoryProjectionRecord as MemoryProjectionRecord

_MODEL_MODULES = (
    "pi_memory.db.models.analysis",
    "pi_memory.db.models.durable",
    "pi_memory.db.models.ingestion",
    "pi_memory.db.models.interpretation",
    "pi_memory.db.models.jobs",
    "pi_memory.db.models.projection",
)


def ensure_models_registered() -> None:
    """Load model modules into Base metadata."""
    for module_name in _MODEL_MODULES:
        import_module(module_name)
