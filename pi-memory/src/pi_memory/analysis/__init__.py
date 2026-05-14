"""Pure transcript analysis helpers for pi-memory."""

from pi_memory.analysis.activity import NormalizedActivity, normalize_transcript_entries
from pi_memory.analysis.episodes import NormalizedEpisode, segment_activities
from pi_memory.analysis.manifests import (
    MANIFEST_HEAD_ACTIVITIES,
    MANIFEST_TAIL_ACTIVITIES,
    MANIFEST_VERSION,
    MAX_MANIFEST_ACTIVITIES,
    BuiltEpisodeManifest,
    BuiltSessionSnapshotShell,
    build_episode_manifest,
    build_episode_manifests,
    build_session_snapshot_shell,
)
from pi_memory.analysis.persistence import TranscriptAnalysisResult, analyze_transcript_structure

__all__ = [
    "MANIFEST_HEAD_ACTIVITIES",
    "MANIFEST_TAIL_ACTIVITIES",
    "MANIFEST_VERSION",
    "MAX_MANIFEST_ACTIVITIES",
    "BuiltEpisodeManifest",
    "BuiltSessionSnapshotShell",
    "NormalizedActivity",
    "NormalizedEpisode",
    "TranscriptAnalysisResult",
    "analyze_transcript_structure",
    "build_episode_manifest",
    "build_episode_manifests",
    "build_session_snapshot_shell",
    "normalize_transcript_entries",
    "segment_activities",
]
