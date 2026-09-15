import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

/** Finding priority: 0 is the most severe, 3 the least. */
export type ReviewPriority = 0 | 1 | 2 | 3;

/** Overall correctness verdict for the reviewed change. */
export type OverallCorrectness = "correct" | "incorrect";

/** How collection of user feedback on the findings ended. */
export type FeedbackStatus = "submitted" | "cancelled" | "unavailable" | "not_required";

/**
 * A single review finding exactly as the model reports it. Finding ids and
 * user feedback are never model-supplied: ids are assigned by the tool after
 * sorting, and feedback comes from the interactive navigator.
 */
export interface ReviewFindingInput {
	title: string;
	body: string;
	priority: ReviewPriority;
	confidence: number;
	file_path: string;
	line_start: number;
	line_end: number;
}

/** Model-facing payload of the review findings tool. */
export interface ReviewFindingsInput {
	scope: string;
	overall_correctness: OverallCorrectness;
	explanation: string;
	confidence: number;
	findings: ReviewFindingInput[];
}

/** A finding after the tool assigned its deterministic id. */
export interface IdentifiedReviewFinding extends ReviewFindingInput {
	id: string;
}

/** A fully prepared review: findings sorted deterministically and id'ed. */
export interface PreparedReview {
	scope: string;
	overall_correctness: OverallCorrectness;
	explanation: string;
	confidence: number;
	findings: IdentifiedReviewFinding[];
}

/** Per-finding user feedback recorded by the interactive navigator. */
export interface ReviewFindingFeedback {
	comment: string | null;
}

/** An artifact finding: the identified finding plus its user feedback. */
export interface ReviewArtifactFinding extends IdentifiedReviewFinding {
	feedback: ReviewFindingFeedback;
}

/**
 * Canonical persisted review artifact. Carries no timestamps or other
 * run-specific data so the artifact is reproducible from its inputs.
 */
export interface ReviewArtifactV1 {
	schema_version: 1;
	scope: string;
	overall_correctness: OverallCorrectness;
	explanation: string;
	confidence: number;
	feedback_status: FeedbackStatus;
	findings: ReviewArtifactFinding[];
}

/** Finding counts keyed by priority. */
export interface PriorityCounts {
	0: number;
	1: number;
	2: number;
	3: number;
}

type ArkType = ExtensionAPI["arktype"];

/**
 * Build the strict model-facing parameter schema with OMP's native omptype
 * builder. Unknown fields are rejected at every object level; finding ids
 * and feedback have no schema fields at all.
 */
export function createReviewFindingsParameters(type: ArkType) {
	const finding = type({
		title: type("string > 0").describe("Concise issue title, ideally at most 80 characters."),
		body: type("string > 0").describe("Detailed explanation of the issue, why it matters, and how to fix it."),
		priority: type("0 | 1 | 2 | 3").describe(
			"OMP-native priority: 0 blocks release or operations, 1 is high and should be fixed next cycle, 2 is medium and should be fixed eventually, 3 is informational and nice to have.",
		),
		confidence: type("0 <= number <= 1").describe(
			"Confidence that this finding identifies a real problem, from 0 to 1.",
		),
		file_path: type("string > 0").describe("Repository-relative path of the file containing the finding."),
		line_start: type("number.integer >= 1").describe("First line of the finding's line range (1-based, inclusive)."),
		line_end: type("number.integer >= 1").describe(
			"Last line of the finding's line range (1-based, inclusive); must be >= line_start.",
		),
		"+": "reject",
	});
	return type({
		scope: type("string > 0").describe("What was reviewed, e.g. the branch or diff range the findings cover."),
		overall_correctness: type("'correct' | 'incorrect'").describe(
			"Whether the reviewed change is correct overall: 'correct' or 'incorrect'.",
		),
		explanation: type("string > 0").describe("One or two sentences explaining the overall correctness verdict."),
		confidence: type("0 <= number <= 1").describe("Confidence in the overall correctness verdict, from 0 to 1."),
		findings: finding
			.array()
			.describe(
				"Final findings after validating them against the code, discarding false positives, and semantically deduplicating shared root causes. Pass an empty array when none remain; the tool sorts findings and assigns ids.",
			),
		"+": "reject",
	}).narrow((review, ctx) => {
		const reversed = review.findings.find((item) => item.line_end < item.line_start);
		return (
			reversed === undefined ||
			ctx.mustBe(
				`finding ${JSON.stringify(reversed.title)} in ${reversed.file_path} to use a line_end greater than or equal to line_start`,
			)
		);
	});
}
