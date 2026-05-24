"""Transcript processing pipeline stage."""

from __future__ import annotations

from typing import Any

from pi_memory.analysis import analyze_transcript_structure
from pi_memory.constants import JOB_KIND_PROCESS_TRANSCRIPT
from pi_memory.db.models import (
    Job,
    Transcript,
)
from pi_memory.infra.job_runner import JobExecutionContext
from pi_memory.pipeline.runtime.errors import TranscriptNotFoundError
from pi_memory.pipeline.utils import payloads
from pi_memory.recall import index_transcript


class ProcessTranscriptJob:
    """Analyze and index a newly observed transcript."""

    kind = JOB_KIND_PROCESS_TRANSCRIPT

    def run(self, context: JobExecutionContext, job: Job) -> dict[str, Any]:
        transcript_id = payloads.transcript_id(job.payload_json)
        context.database.initialize()
        with context.database.session() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise TranscriptNotFoundError(transcript_id)

            index_result = index_transcript(session, transcript_id)
            analysis_result = analyze_transcript_structure(session, transcript, job_id=job.id)
            return {
                "transcript_id": transcript.id,
                "session_id": transcript.session.session_id,
                "entry_count": index_result.total_entries,
                "cursor_offset": transcript.cursor_offset,
                "file_size": transcript.file_size,
                "indexed_entry_count": index_result.indexed_entries,
                "phase_5a": analysis_result.to_result_json(),
            }

