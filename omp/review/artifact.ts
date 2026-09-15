import type {
	FeedbackStatus,
	IdentifiedReviewFinding,
	PreparedReview,
	PriorityCounts,
	ReviewArtifactFinding,
	ReviewArtifactV1,
	ReviewFindingInput,
	ReviewFindingsInput,
} from "./schema.ts";

function compareFindings(left: ReviewFindingInput, right: ReviewFindingInput): number {
	if (left.priority !== right.priority) return left.priority - right.priority;
	if (left.file_path !== right.file_path) return left.file_path < right.file_path ? -1 : 1;
	if (left.line_start !== right.line_start) return left.line_start - right.line_start;
	if (left.line_end !== right.line_end) return left.line_end - right.line_end;
	if (left.title !== right.title) return left.title < right.title ? -1 : 1;
	return 0;
}

/**
 * Sort findings deterministically (priority, path, start, end, title) and
 * assign sequential ids (`finding-1`, `finding-2`, ...) in sorted order. The
 * input is not mutated.
 */
export function prepareReview(input: ReviewFindingsInput): PreparedReview {
	const findings = [...input.findings]
		.sort(compareFindings)
		.map((finding, index): IdentifiedReviewFinding => ({ ...finding, id: `finding-${index + 1}` }));
	return {
		scope: input.scope,
		overall_correctness: input.overall_correctness,
		explanation: input.explanation,
		confidence: input.confidence,
		findings,
	};
}

/** Count findings per priority; all four priorities are always present. */
export function reviewPriorityCounts(findings: readonly ReviewFindingInput[]): PriorityCounts {
	const counts: PriorityCounts = { 0: 0, 1: 0, 2: 0, 3: 0 };
	for (const finding of findings) counts[finding.priority] += 1;
	return counts;
}

/**
 * Build the canonical schema_version 1 artifact from a prepared review, the
 * navigator's feedback status, and navigator comments keyed by finding id.
 * Comments for unknown ids are ignored; findings without a comment get null.
 */
export function buildReviewArtifact(
	prepared: PreparedReview,
	status: FeedbackStatus,
	comments: Readonly<Record<string, string>> = {},
): ReviewArtifactV1 {
	const findings: ReviewArtifactFinding[] = prepared.findings.map((finding) => ({
		...finding,
		feedback: { comment: comments[finding.id] ?? null },
	}));
	return {
		schema_version: 1,
		scope: prepared.scope,
		overall_correctness: prepared.overall_correctness,
		explanation: prepared.explanation,
		confidence: prepared.confidence,
		feedback_status: status,
		findings,
	};
}
