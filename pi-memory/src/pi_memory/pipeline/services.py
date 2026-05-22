"""Pipeline dependency providers."""

from __future__ import annotations

from dataclasses import dataclass, field

from pi_memory.durable import (
    CandidateEvaluator,
    DeterministicDurableMemoryReducer,
    create_candidate_evaluator,
)
from pi_memory.interpretation import (
    SessionInterpreter,
    ToolActivitySummarizer,
    create_session_interpreter,
    create_tool_activity_summarizer,
)
from pi_memory.projection import create_memory_projection
from pi_memory.projection.contracts import MemoryProjection
from pi_memory.quality import QualityAssessor, create_quality_assessor


@dataclass
class PipelineServices:
    """Lazy providers for executable memory pipeline stages."""

    interpreter: SessionInterpreter | None = None
    tool_summarizer: ToolActivitySummarizer | None = None
    quality_assessor: QualityAssessor | None = None
    memory_projection_adapter: MemoryProjection | None = None
    candidate_evaluator_adapter: CandidateEvaluator | None = None
    durable_reducer: DeterministicDurableMemoryReducer = field(
        default_factory=DeterministicDurableMemoryReducer,
    )

    def session_interpreter(self) -> SessionInterpreter:
        if self.interpreter is not None:
            return self.interpreter
        return create_session_interpreter()

    def tool_activity_summarizer(self) -> ToolActivitySummarizer:
        if self.tool_summarizer is not None:
            return self.tool_summarizer
        return create_tool_activity_summarizer()

    def interpretation_quality_assessor(self) -> QualityAssessor:
        if self.quality_assessor is not None:
            return self.quality_assessor
        return create_quality_assessor()

    def memory_projection(self) -> MemoryProjection:
        if self.memory_projection_adapter is None:
            self.memory_projection_adapter = create_memory_projection()
        return self.memory_projection_adapter

    def candidate_evaluator(self) -> CandidateEvaluator:
        if self.candidate_evaluator_adapter is None:
            self.candidate_evaluator_adapter = create_candidate_evaluator()
        return self.candidate_evaluator_adapter
