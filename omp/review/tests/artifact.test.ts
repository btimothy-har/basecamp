import { describe, expect, test } from "bun:test";
import { buildReviewArtifact, prepareReview, reviewPriorityCounts } from "../artifact.ts";
import type { FeedbackStatus, ReviewFindingInput, ReviewFindingsInput } from "../schema.ts";

function finding(overrides: Partial<ReviewFindingInput> = {}): ReviewFindingInput {
	return {
		title: "title",
		body: "body",
		recommendation: "Apply the focused fix.",
		priority: 1,
		confidence: 0.5,
		file_path: "a.ts",
		line_start: 1,
		line_end: 1,
		...overrides,
	};
}

function input(findings: ReviewFindingInput[]): ReviewFindingsInput {
	return {
		scope: "main...HEAD",
		overall_correctness: "incorrect",
		explanation: "The change has problems.",
		recommendation: "Fix the validated findings before merging.",
		confidence: 0.9,
		findings,
	};
}

// Exercises every sort key in order: priority, file_path, line_start,
// line_end, then title.
const scrambledFindings: ReviewFindingInput[] = [
	finding({ file_path: "a.ts", line_start: 2, title: "later start" }),
	finding({ file_path: "a.ts", line_start: 1, line_end: 1, title: "b title" }),
	finding({ file_path: "z.ts", priority: 0, title: "highest priority in z" }),
	finding({ file_path: "a.ts", line_start: 1, line_end: 2, title: "longer range" }),
	finding({ file_path: "a.ts", line_start: 1, line_end: 1, title: "a title" }),
	finding({ file_path: "b.ts", line_start: 1, title: "other file" }),
];

const expectedOrder = ["highest priority in z", "a title", "b title", "longer range", "later start", "other file"];

describe("prepareReview", () => {
	test("sorts deterministically by priority, path, start, end, title and assigns sequential ids", () => {
		const prepared = prepareReview(input(scrambledFindings));
		expect(prepared.findings.map((f) => f.title)).toEqual(expectedOrder);
		expect(prepared.findings.map((f) => f.id)).toEqual([
			"finding-1",
			"finding-2",
			"finding-3",
			"finding-4",
			"finding-5",
			"finding-6",
		]);
	});

	test("produces identical output for permuted input", () => {
		const forward = prepareReview(input(scrambledFindings));
		const reversed = prepareReview(input([...scrambledFindings].reverse()));
		expect(reversed).toEqual(forward);
	});

	test("does not mutate the input or add ids to it", () => {
		const findings = scrambledFindings.map((f) => ({ ...f }));
		const originalOrder = findings.map((f) => f.title);
		prepareReview(input(findings));
		expect(findings.map((f) => f.title)).toEqual(originalOrder);
		expect(findings.some((f) => "id" in f)).toBe(false);
	});

	test("carries the review-level fields through unchanged", () => {
		const prepared = prepareReview(input([finding()]));
		expect(prepared.scope).toBe("main...HEAD");
		expect(prepared.overall_correctness).toBe("incorrect");
		expect(prepared.explanation).toBe("The change has problems.");
		expect(prepared.recommendation).toBe("Fix the validated findings before merging.");
		expect(prepared.confidence).toBe(0.9);
	});
});

describe("reviewPriorityCounts", () => {
	test("tallies each priority with all four keys present", () => {
		const counts = reviewPriorityCounts([
			finding({ priority: 0 }),
			finding({ priority: 0 }),
			finding({ priority: 2 }),
			finding({ priority: 3 }),
		]);
		expect(counts).toEqual({ 0: 2, 1: 0, 2: 1, 3: 1 });
	});

	test("returns zero counts for no findings", () => {
		expect(reviewPriorityCounts([])).toEqual({ 0: 0, 1: 0, 2: 0, 3: 0 });
	});
});

describe("buildReviewArtifact", () => {
	test("attaches comments to findings by id and leaves the rest null", () => {
		const prepared = prepareReview(input(scrambledFindings));
		const artifact = buildReviewArtifact(prepared, "submitted", {
			"finding-3": "Please expand on this.",
			"finding-5": "Not sure this matters.",
		});
		const comments = artifact.findings.map((f) => [f.id, f.feedback.comment] as const);
		expect(comments).toEqual([
			["finding-1", null],
			["finding-2", null],
			["finding-3", "Please expand on this."],
			["finding-4", null],
			["finding-5", "Not sure this matters."],
			["finding-6", null],
		]);
	});

	test("ignores comments for unknown ids", () => {
		const prepared = prepareReview(input([finding()]));
		const artifact = buildReviewArtifact(prepared, "submitted", { "finding-99": "stray" });
		expect(artifact.findings[0]?.feedback.comment).toBeNull();
	});

	test("carries every feedback status through", () => {
		const prepared = prepareReview(input([finding()]));
		const statuses: FeedbackStatus[] = ["submitted", "cancelled", "unavailable", "not_required"];
		for (const status of statuses) {
			expect(buildReviewArtifact(prepared, status, {}).feedback_status).toBe(status);
		}
	});

	test("produces the canonical schema_version 2 shape without timestamps", () => {
		const prepared = prepareReview(input([finding({ priority: 2 })]));
		const artifact = buildReviewArtifact(prepared, "cancelled");
		expect(artifact).toEqual({
			schema_version: 2,
			scope: "main...HEAD",
			overall_correctness: "incorrect",
			explanation: "The change has problems.",
			recommendation: "Fix the validated findings before merging.",
			confidence: 0.9,
			feedback_status: "cancelled",
			findings: [
				{
					id: "finding-1",
					title: "title",
					body: "body",
					recommendation: "Apply the focused fix.",
					priority: 2,
					confidence: 0.5,
					file_path: "a.ts",
					line_start: 1,
					line_end: 1,
					feedback: { comment: null },
				},
			],
		});
	});
});
