"""Search indexing pipeline — embeds artifact sections into ChromaDB.

Reads artifacts that need embedding, encodes with sentence-transformers,
and upserts into the ChromaDB collection with metadata for filtering.
"""

import hashlib
import logging
from datetime import UTC, datetime

from observer.constants import EMBEDDING_DIMENSIONS
from observer.data.artifact import Artifact
from observer.data.schemas import ArtifactSchema, ProjectSchema, TranscriptSchema, WorktreeSchema
from observer.exceptions import EmbeddingShapeError
from observer.services.chroma import get_collection
from observer.services.db import Database
from observer.services.embedding import get_model

logger = logging.getLogger(__name__)


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _resolve_metadata(db: Database, artifact_ids: list[int]) -> dict[int, dict]:
    """Resolve ChromaDB metadata for a batch of artifacts by joining through transcript."""
    if not artifact_ids:
        return {}

    metadata = {}
    with db.session() as session:
        rows = (
            session.query(
                ArtifactSchema.id,
                ArtifactSchema.transcript_id,
                ArtifactSchema.section_type,
                TranscriptSchema.session_id,
                TranscriptSchema.started_at,
                ProjectSchema.name.label("project_name"),
                WorktreeSchema.label.label("worktree_label"),
            )
            .join(TranscriptSchema, ArtifactSchema.transcript_id == TranscriptSchema.id)
            .join(ProjectSchema, TranscriptSchema.project_id == ProjectSchema.id)
            .outerjoin(WorktreeSchema, TranscriptSchema.worktree_id == WorktreeSchema.id)
            .filter(ArtifactSchema.id.in_(artifact_ids))
            .all()
        )
        for row in rows:
            meta = {
                "artifact_id": row.id,
                "transcript_id": row.transcript_id,
                "section_type": str(row.section_type),
                "session_id": row.session_id,
                "project_name": row.project_name,
                "started_at": row.started_at.timestamp() if row.started_at else 0.0,
            }
            if row.worktree_label is not None:
                meta["worktree_label"] = row.worktree_label
            metadata[row.id] = meta

    return metadata


class SearchIndexer:
    """Embeds artifacts for semantic search via ChromaDB."""

    @staticmethod
    def has_pending() -> bool:
        """Check if any artifacts need embedding."""
        return Artifact.has_pending_index()

    @staticmethod
    def index_pending(
        db: Database,
        *,
        transcript_id: int | None = None,
    ) -> int:
        """Embed pending artifacts. Returns count of rows indexed."""
        to_index = Artifact.get_pending_index(transcript_id=transcript_id)

        if not to_index:
            return 0

        texts = [a.text for a in to_index]
        embeddings = _encode(texts)

        # Resolve metadata for ChromaDB
        artifact_ids = [a.id for a in to_index]
        metadata_map = _resolve_metadata(db, artifact_ids)

        # Upsert into ChromaDB
        collection = get_collection()
        chroma_ids = [str(a.id) for a in to_index]
        chroma_embeddings = [e.tolist() for e in embeddings]
        chroma_metadatas = [metadata_map.get(a.id, {}) for a in to_index]
        chroma_documents = texts

        collection.upsert(
            ids=chroma_ids,
            embeddings=chroma_embeddings,
            metadatas=chroma_metadatas,
            documents=chroma_documents,
        )

        # Update content_hash and indexed_at in SQLite
        now = datetime.now(UTC)
        with db.session() as session:
            for artifact in to_index:
                artifact.update_index_metadata(
                    session,
                    content_hash=_content_hash(artifact.text),
                    indexed_at=now,
                )

        logger.info("Indexed %d artifacts", len(to_index))
        return len(to_index)


def _encode(texts: list[str]) -> list:
    """Encode texts into embedding vectors. Lazy-loads model."""
    model = get_model()
    embeddings = model.encode(texts, show_progress_bar=False)

    expected = (len(texts), EMBEDDING_DIMENSIONS)
    if embeddings.shape != expected:
        raise EmbeddingShapeError(expected, embeddings.shape)

    return embeddings
